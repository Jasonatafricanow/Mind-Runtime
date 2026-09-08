"""C5B CLI wiring tests: proactive tick flag + config loaders (argv-injected).

Covers the new main() branches (STEP 7/8): gate off, missing config, JSON
config loading, and one full gated tick pass over a temp runtime dir.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.contracts import (
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.shadow import runtime_loop

BASE = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

_TICK_CONFIG = {
    "rules": [
        {
            "rule_id": "reach-out",
            "kind": "reach_out",
            "base_strength": 0.1,
            "dimension_weights": [{"dimension": "agent.affect.missing", "weight": 1.0}],
            "event_kind": None,
            "event_bonus": 0.0,
            "minimum_strength": 0.8,
            "due_at_attribute": None,
            "expires_after_seconds": None,
            "reconsideration_policy": "never",
        }
    ],
    "policy": {
        "rules": [
            {
                "intent_kind": "reach_out",
                "action_type": "proactive_message",
                "proactive": True,
                "interrupts_active_conversation": False,
                "media_counter_fact": None,
                "media_limit": None,
                "required_resource": None,
            }
        ],
        "proactive_cooldown_seconds": 1800,
    },
    "resources": ["proactive_message", "respond"],
}


def _write_config(tmp_path: Path) -> str:
    path = tmp_path / "tick-config.json"
    path.write_text(json.dumps(_TICK_CONFIG), encoding="utf-8")
    return str(path)


def _seed_persona(tmp_path: Path) -> str:
    """Minimal synthetic agent-domain persona (no Kayla strings)."""
    persona = {
        "persona_id": "synthetic-tick",
        "profile_version": 1,
        "dimensions": [
            {
                "dimension": "agent.affect.missing",
                "baseline": 0.9,
                "initial_value": 0.6,
                "sensitivity": 1.0,
                "recovery_rate": 0.02,
                "ceiling": 1.0,
                "floor": 0.0,
                "growth_profile": [],
                "coupling_profile": [],
            }
        ],
    }
    path = tmp_path / "persona.json"
    path.write_text(json.dumps(persona), encoding="utf-8")
    return str(path)


def _seed_affect_row(facts_db: str, cognition_db: str) -> None:
    """Seed one durable affect row so the tick has elapsed truth to advance."""

    from mind_runtime.contracts import RuntimeState
    from mind_runtime.state.persistence import SqliteStateBackend

    backend = SqliteStateBackend(cognition_db)
    scope = Scope(
        domain=ScopeDomain.AGENT, agent_id="synthetic-tick", persona_id="synthetic-tick"
    )
    state_id = "agent.affect.missing:1:seeded"
    at = BASE - timedelta(hours=2)
    backend.save_state(
        RuntimeState(
            state_id=state_id,
            scope=scope,
            dimension="agent.affect.missing",
            value=0.75,
            status="active",
            valid_from=at,
            valid_until=None,
            relevant_until=None,
            last_observed_at=at,
            evidence_refs=(),
            transition_refs=(),
            updated_at=at,
            origin_runtime_id="kayla",
            version=1,
            sync=SyncFields(scope, "kayla", state_id, 1, f"idem-{state_id}"),
        )
    )


def test_cli_tick_flag_without_config_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--proactive-tick without --intent-rules-json refuses to build."""
    from mind_runtime.shadow.redaction import init_store

    shadow_db = tmp_path / "shadow.db"
    init_store(shadow_db)
    monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_INGEST", "1")
    monkeypatch.setenv(runtime_loop.PROACTIVE_TICK_ENV, "1")
    with pytest.raises(ValueError, match="--(intent-rules-json|persona-json)"):
        runtime_loop.main(
            [
                "--shadow-db",
                str(shadow_db),
                "--facts-db",
                str(tmp_path / "facts.sqlite"),
                "--cognition-db",
                str(tmp_path / "cog.sqlite"),
                "--blocked-db",
                str(tmp_path / "blocked.sqlite3"),
                "--proactive-tick",
            ]
        )


def test_cli_tick_gate_off_reports_and_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from mind_runtime.shadow.redaction import init_store

    shadow_db = tmp_path / "shadow.db"
    init_store(shadow_db)
    monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_INGEST", "1")
    monkeypatch.delenv(runtime_loop.PROACTIVE_TICK_ENV, raising=False)
    config = _write_config(tmp_path)
    runtime_loop.main(
        [
            "--shadow-db",
            str(tmp_path / "shadow.db"),
            "--facts-db",
            str(tmp_path / "facts.sqlite"),
            "--cognition-db",
            str(tmp_path / "cog.sqlite"),
            "--blocked-db",
            str(tmp_path / "blocked.sqlite3"),
            "--proactive-tick",
            "--intent-rules-json",
            config,
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["proactive_tick"] == {"gate": "off"}


def test_cli_config_loaders_roundtrip(tmp_path: Path) -> None:
    """The three JSON loaders reproduce valid rule/policy/resources objects."""
    import argparse

    from mind_runtime.contracts import ReconsiderationPolicy

    config = _write_config(tmp_path)
    args = argparse.Namespace(intent_rules_json=config)
    rules = runtime_loop.tick_config_rules(args)
    assert len(rules) == 1
    assert rules[0].rule_id == "reach-out"
    assert rules[0].reconsideration_policy is ReconsiderationPolicy.NEVER
    assert rules[0].expires_after is None

    policy = runtime_loop.tick_config_policy(args)
    assert policy.proactive_cooldown == timedelta(minutes=30)
    assert policy.rules[0].action_type == "proactive_message"

    resources = runtime_loop.tick_config_resources(args)
    assert resources == ("proactive_message", "respond")
