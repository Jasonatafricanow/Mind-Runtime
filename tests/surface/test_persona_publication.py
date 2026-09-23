"""ADR-0029: immutable config revision and cross-process conflict proofs."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from mind_runtime.persona_config import load_persona_profile
from mind_runtime.persona_publication import (
    PersonaConfigPublicationRepository,
    PersonaRevisionConflict,
    PersonaRevisionRef,
    ReplayUnavailable,
)
from mind_runtime.binding_registry import BindingRegistry
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment


def _profile(approach: float) -> dict:
    return {
        "schema_version": 2, "profile_version": 2,
        "persona_id": "publication-fixture",
        "dimensions": [{
            "dimension": "agent.affect.longing", "baseline": 0.0,
            "initial_value": 0.0, "sensitivity": 1.0,
            "recovery_rate": 0.0, "floor": 0.0, "ceiling": 1.0,
            "growth_profile": [], "coupling_profile": [],
        }],
        "behavioral_disposition": {
            "attachment_approach": approach,
            "confrontation_readiness": 0.5,
            "expressive_restraint": 0.4,
            "expressive_warmth_bias": 0.5,
        },
    }


def _write(path: Path, profile: dict) -> Path:
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def _process(root: Path, action: str, source: str, version: int = 2, digest: str = ""):
    repo_root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
    program = (
        "from mind_runtime.persona_publication import PersonaConfigPublicationRepository,PersonaRevisionRef;"
        "import sys;r=PersonaConfigPublicationRepository(sys.argv[1]);"
        "v=r.publish(sys.argv[3]) if sys.argv[2]=='publish' else "
        "r.resolve(PersonaRevisionRef(sys.argv[3],int(sys.argv[4]),sys.argv[5]));"
        "print(v.effective_content_digest)"
    )
    return subprocess.run(
        [sys.executable, "-c", program, str(root), action, source, str(version), digest],
        cwd=repo_root, env=env, capture_output=True, text=True, check=False,
    )


def test_create_once_across_processes(tmp_path: Path) -> None:
    root = tmp_path / "published"
    a = _write(tmp_path / "a.json", _profile(0.2))
    b = _write(tmp_path / "b.json", _profile(0.8))
    first = _process(root, "publish", str(a))
    assert first.returncode == 0, first.stderr
    digest = first.stdout.strip()
    same = _process(root, "publish", str(a))
    assert same.returncode == 0, same.stderr
    assert same.stdout.strip() == digest
    conflict = _process(root, "publish", str(b))
    assert conflict.returncode != 0
    assert "PERSONA_REVISION_CONFLICT" in conflict.stderr
    restored = _process(root, "resolve", "publication-fixture", 2, digest)
    assert restored.returncode == 0, restored.stderr
    assert restored.stdout.strip() == digest


def test_missing_artifact_fails_without_mutable_alias_fallback(tmp_path: Path) -> None:
    source = _write(tmp_path / "current.json", _profile(0.2))
    loaded = load_persona_profile(source, registry=None)
    ref = PersonaRevisionRef(loaded.persona_id, loaded.profile_version,
                             loaded.effective_content_digest)
    repo = PersonaConfigPublicationRepository(tmp_path / "published")
    with pytest.raises(ReplayUnavailable, match="REPLAY_UNAVAILABLE"):
        repo.resolve(ref)
    assert repo.publish(source) == ref
    assert repo.resolve(ref).effective_content_digest == ref.effective_content_digest
    artifact = repo.artifact_path(ref)
    artifact.chmod(0o666)  # test simulates loss of a historical artifact
    artifact.unlink()
    with pytest.raises(ReplayUnavailable, match="REPLAY_UNAVAILABLE"):
        repo.resolve(ref)


def test_restart_binding_resolves_exact_published_revision(tmp_path: Path) -> None:
    source = _write(tmp_path / "fixture.json", _profile(0.2))
    published = PersonaConfigPublicationRepository(tmp_path / "published")
    ref = published.publish(source)
    binding = RuntimeBinding(
        persona_id=ref.persona_id, agent_id="fixture-agent",
        runtime_id="fixture-runtime", storage_namespace="lab/fixture-runtime",
        environment=RuntimeEnvironment.LAB,
    )
    registry = BindingRegistry(tmp_path / "bindings")
    registry.initialize()
    registry.register(binding, "fixture-binding")
    registry.pin_persona_revision("fixture-binding", ref)
    restored = BindingRegistry(tmp_path / "bindings")
    exact = restored.resolve_persona_revision(
        "fixture-binding", environment=RuntimeEnvironment.LAB
    )
    assert exact == ref
    assert published.resolve(exact).profile == load_persona_profile(source, registry=None).profile
    with pytest.raises(PersonaRevisionConflict, match="PERSONA_REVISION_CONFLICT"):
        restored.pin_persona_revision(
            "fixture-binding",
            PersonaRevisionRef(ref.persona_id, ref.profile_version, "0" * 64),
        )


def test_competing_processes_cannot_replace_pinned_revision(tmp_path: Path) -> None:
    binding = RuntimeBinding(
        persona_id="publication-fixture", agent_id="fixture-agent",
        runtime_id="fixture-runtime", storage_namespace="lab/fixture-runtime",
        environment=RuntimeEnvironment.LAB,
    )
    root = tmp_path / "bindings"
    registry = BindingRegistry(root)
    registry.initialize()
    registry.register(binding, "fixture-binding")
    repo_root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
    program = (
        "from mind_runtime.binding_registry import BindingRegistry;"
        "from mind_runtime.persona_publication import PersonaRevisionRef;"
        "import sys;BindingRegistry(sys.argv[1]).pin_persona_revision("
        "'fixture-binding',PersonaRevisionRef('publication-fixture',2,sys.argv[2]));"
        "print(sys.argv[2])"
    )
    digests = ("a" * 64, "b" * 64)
    processes = [subprocess.Popen(
        [sys.executable, "-c", program, str(root), digest], cwd=repo_root,
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) for digest in digests]
    results = [process.communicate() for process in processes]
    successes = [i for i, process in enumerate(processes) if process.returncode == 0]
    assert len(successes) == 1, results
    assert "PERSONA_REVISION_CONFLICT" in results[1 - successes[0]][1]
    persisted = BindingRegistry(root).resolve_persona_revision(
        "fixture-binding", environment=RuntimeEnvironment.LAB,
    )
    assert persisted.effective_content_digest == digests[successes[0]]
