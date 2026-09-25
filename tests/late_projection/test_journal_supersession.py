"""Explicit appraisal supersession preserves audit rows and prevents stale reuse."""

from dataclasses import replace

import pytest
from tests.late_projection.test_foundation import accepted, projector

from mind_runtime.contracts.late_projection import canonical_json, digest
from mind_runtime.emotional_transition.projection_journal import ProjectionJournal


def revised(record, **changes):
    record = replace(record, **changes)
    return replace(
        record,
        acceptance_id="acceptance-"
        + digest(
            (
                record.appraisal,
                record.candidate,
                record.interaction_id,
                record.persona_id,
                record.trusted_evidence_refs,
                record.route_abstention_reasons,
                record.status,
                record.reason_codes,
                record.projection_scope,
            )
        ),
    )


def newer(record):
    return revised(record, appraisal=replace(record.appraisal, meanings=("reconsidered",)))


def save(journal, record):
    return journal.materialize(projector(), acceptance=record, history=None)


def test_explicit_supersession_survives_restart_and_rejects_old_cache(tmp_path):
    path = tmp_path / "journal.sqlite"
    old = accepted()
    new = newer(old)
    journal = ProjectionJournal(path)
    original = save(journal, old)
    journal.supersede(old_acceptance_id=old.acceptance_id, acceptance=new)
    assert save(journal, new).source_appraisal_ref == new.appraisal.appraisal_id
    journal.close()
    journal = ProjectionJournal(path)
    assert (
        journal.find_acceptance(
            candidate=old.candidate, interaction_id=old.interaction_id, persona_id=old.persona_id
        )
        == new
    )
    assert journal.get_acceptance(old.acceptance_id) == old
    assert journal.get_projection(original.projection_id) == original
    with pytest.raises(ValueError, match="superseded"):
        save(journal, old)
    journal.close()


def test_changed_acceptance_requires_explicit_supersession():
    journal = ProjectionJournal()
    old = accepted()
    save(journal, old)
    with pytest.raises(ValueError, match="conflict|supersession"):
        save(journal, newer(old))


def test_lookup_rejects_changed_input_payload():
    journal = ProjectionJournal()
    old = accepted()
    save(journal, old)
    with pytest.raises(ValueError, match="payload conflict"):
        journal.find_acceptance(
            candidate=replace(old.candidate, confidence=0.3),
            interaction_id=old.interaction_id,
            persona_id=old.persona_id,
        )


@pytest.mark.parametrize("change", ("candidate", "interaction", "persona", "runtime"))
def test_supersession_rejects_different_source(change):
    journal = ProjectionJournal()
    old = accepted()
    save(journal, old)
    changes = {
        "candidate": {"candidate": replace(old.candidate, confidence=0.4)},
        "interaction": {"interaction_id": "other"},
        "persona": {"persona_id": "other"},
        "runtime": {
            "candidate": replace(old.candidate, origin_runtime_id="other"),
            "appraisal": replace(old.appraisal, origin_runtime_id="other"),
        },
    }
    with pytest.raises(ValueError, match="source|payload"):
        journal.supersede(
            old_acceptance_id=old.acceptance_id, acceptance=revised(newer(old), **changes[change])
        )


def test_lookup_rejects_ambiguous_existing_rows():
    journal = ProjectionJournal()
    old = accepted()
    new = newer(old)
    save(journal, old)
    with journal.connection:
        journal.connection.execute(
            "INSERT INTO appraisal_evaluations VALUES (?,?,?,?)",
            (
                new.acceptance_id,
                new.interaction_id,
                new.candidate.candidate_id,
                canonical_json(new),
            ),
        )
    with pytest.raises(ValueError, match="ambiguous"):
        journal.find_acceptance(
            candidate=old.candidate, interaction_id=old.interaction_id, persona_id=old.persona_id
        )


def test_supersession_is_idempotent_but_cannot_branch_or_reverse():
    journal = ProjectionJournal()
    old = accepted()
    new = newer(old)
    save(journal, old)
    journal.supersede(old_acceptance_id=old.acceptance_id, acceptance=new)
    journal.supersede(old_acceptance_id=old.acceptance_id, acceptance=new)
    with pytest.raises(ValueError, match="superseded|conflict"):
        journal.supersede(
            old_acceptance_id=old.acceptance_id,
            acceptance=revised(new, reason_codes=("different",)),
        )
    with pytest.raises(ValueError, match="superseded|cycle"):
        journal.supersede(old_acceptance_id=new.acceptance_id, acceptance=old)


def test_projection_with_wrong_source_is_rejected_before_persistence():
    journal = ProjectionJournal()
    old = accepted()
    p = projector()
    original = p.project
    p.project = lambda **kwargs: replace(original(**kwargs), source_candidate_ref="foreign")
    with pytest.raises(ValueError, match="source|identity"):
        journal.materialize(p, acceptance=old, history=None)
    # W2 journals acceptance first; forged projection remains rejected.
    assert journal.get_acceptance(old.acceptance_id) == old
