"""OW-UI-1 R1: Real-MR Web console entry point.

This is the **daily-use command** (per OW-UI-1-R1 spec):

    python -m observation_window.web.runtime

It binds the OW-UI-1 Web API to the real MR SQLite backends. The API
reads the same durable data that a live ``TurnOrchestrator`` writes to
via ``SqliteStateBackend`` / ``SqliteFactBackend`` /
``SqliteCommitMarkerStore``.

For the live-trace panel (current-turn / recent-turn / causal-chain
tabs), the host wires a :class:`OrchestratorLiveTraceSink` and calls
:meth:`OrchestratorLiveTraceSink.submit` after each turn commit.
See :func:`wire_live_trace_for_orchestrator` for the one-call hook
pattern.

Zero changes to MR cognitive logic. Zero changes to MR persistence.
The Web API is strictly read-only.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn

from observation_window.web import LiveTraceCache

if TYPE_CHECKING:
    from observation_window.binding import StateSurface
from observation_window.web.wiring import (
    OrchestratorLiveTraceSink,
    build_dashboard_data_sources,
    wire_live_trace_for_orchestrator,
)


log = logging.getLogger("observation_window.web.runtime")


def _patch_sqlite_for_threading() -> None:
    """Allow sqlite3 connections across uvicorn worker threads.

    MR's durable backends use ``check_same_thread=True`` (the safe
    default).  The Web API is read-only, so this relaxation is
    safe for the OW API process.  MR's own durability (writes from
    the orchestrator process) is unaffected.
    """
    real_connect = sqlite3.connect

    def _loose_connect(*a, **kw):
        kw.setdefault("check_same_thread", False)
        return real_connect(*a, **kw)

    sqlite3.connect = _loose_connect


def build_ow_app_from_db_dir(
    db_dir: Path | str,
    *,
    maxlen: int = 200,
    state_surface: "StateSurface | None" = None,
    live_trace_provider: Any = None,
) -> "tuple[object, OrchestratorLiveTraceSink]":  # type: ignore[name-defined]
    """Build the FastAPI app wired to explicit MR SQLite source paths.

    EXPLICIT-SOURCE TEST/COMPAT CONSTRUCTION
    (OW-MULTI-AGENT-BINDING-PHASE01-V1 §7): this helper is NOT production
    identity authority. Production composition must go through
    :func:`compose_ow_app` with a binding resolved by
    :class:`~observation_window.binding.BindingResolver` /
    ``SingleBindingRegistryAdapter``. No discovery happens here: the caller
    names the sources, the binding scope is derived from the given directory,
    and optional sources (telemetry / assistant messages / readiness)
    degrade to component-unavailable.

    Returns the app and the :class:`OrchestratorLiveTraceSink` so the
    host can call :meth:`OrchestratorLiveTraceSink.submit` after each
    turn to populate the live-trace panel.

    The ``db_dir`` should contain at minimum:
        - ``cognition_state.sqlite``   (SqliteStateBackend + SqliteCommitMarkerStore)
        - ``facts.sqlite``             (SqliteFactBackend)

    The directory is created if it does not exist.
    """
    db_dir = Path(db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    state_db = str(db_dir / "cognition_state.sqlite")
    facts_db = str(db_dir / "facts.sqlite")

    _patch_sqlite_for_threading()

    from mind_runtime.facts.persistence import SqliteFactBackend
    from mind_runtime.state.persistence import (
        SqliteCommitMarkerStore,
        SqliteStateBackend,
    )
    from observation_window.binding import (
        AssistantMessageSource,
        ObservationContext,
        StateSurface,
        TelemetrySource,
    )
    from observation_window.live_trace import OWLiveTraceSource

    state_be = SqliteStateBackend(state_db)
    fact_be = SqliteFactBackend(facts_db)
    cm_be = SqliteCommitMarkerStore(state_db)

    cache = LiveTraceCache(maxlen=maxlen)
    live_source = OWLiveTraceSource()
    sink = OrchestratorLiveTraceSink(cache=cache, live_source=live_source)

    sources = build_dashboard_data_sources(
        state_backend=state_be,
        fact_backend=fact_be,
        commit_markers=cm_be,
        sink=sink,
        cache=cache,
    )

    context = ObservationContext(
        binding_scope_key=f"explicit-source:{db_dir.resolve().as_posix()}",
        state_surface=state_surface if state_surface is not None else StateSurface(),
        telemetry_source=TelemetrySource(db_path=None),
        assistant_message_source=AssistantMessageSource(db_path=None),
        runtime_status_provider=_ExplicitSourceStatusProvider(),
        facts_db=Path(facts_db),
        state_db=Path(state_db),
        # Compat mode keeps serving the deployment-truth debug channel via
        # the collector-backed provider (the caller may override it).
        live_trace_provider=(
            live_trace_provider
            if live_trace_provider is not None
            else _default_live_trace_provider()
        ),
    )

    from observation_window.web.api import (
        build_router,
        register_scoped_binding_error_handler,
    )
    from fastapi import FastAPI

    app = FastAPI()
    register_scoped_binding_error_handler(app)
    app.include_router(build_router(sources, context))
    app.state.observation_context = context
    return app, sink


class _ExplicitSourceStatusProvider:
    """UNKNOWN readiness for explicit-source compat construction."""

    def projection(self):
        from observation_window.binding import RuntimeStatusProjection

        return RuntimeStatusProjection(status="UNKNOWN", summary_code="UNKNOWN")


def _default_live_trace_provider():
    """Deployment-truth live-trace provider (read-only collector).

    The factory lives in the deployment-aware collector module, so this
    generic composition module carries no layout knowledge itself.
    """
    from observation_window.live_runtime_trace import live_runtime_trace_provider

    return live_runtime_trace_provider


def compose_ow_app(
    resolved,
    *,
    maxlen: int = 200,
    live_trace_provider=None,
    catalog: Any | None = None,
) -> "tuple[object, OrchestratorLiveTraceSink]":  # type: ignore[name-defined]
    """Production composition (Phase 0/1): binding context → OW app.

    ``resolved`` is a :class:`~observation_window.binding.ResolvedObservationBinding`
    produced by :class:`~observation_window.binding.BindingResolver` from an
    authoritative binding (no paths, no heuristics at this boundary — the
    resolved context already carries the source handles).
    """
    _patch_sqlite_for_threading()

    from mind_runtime.facts.persistence import SqliteFactBackend
    from mind_runtime.state.persistence import (
        SqliteCommitMarkerStore,
        SqliteStateBackend,
    )
    from observation_window.binding import ObservationContext
    from observation_window.live_trace import OWLiveTraceSource

    state_be = SqliteStateBackend(str(resolved.state_db))
    fact_be = SqliteFactBackend(str(resolved.facts_db))
    cm_be = SqliteCommitMarkerStore(str(resolved.state_db))

    cache = LiveTraceCache(maxlen=maxlen)
    live_source = OWLiveTraceSource()
    sink = OrchestratorLiveTraceSink(cache=cache, live_source=live_source)

    sources = build_dashboard_data_sources(
        state_backend=state_be,
        fact_backend=fact_be,
        commit_markers=cm_be,
        sink=sink,
        cache=cache,
    )

    context = ObservationContext.from_resolved(
        resolved,
        live_trace_provider=live_trace_provider,
    )

    from observation_window.web.api import (
        build_router,
        register_scoped_binding_error_handler,
    )
    from fastapi import FastAPI

    app = FastAPI()
    register_scoped_binding_error_handler(app)
    app.include_router(build_router(sources, context, catalog=catalog))
    app.state.observation_context = context
    if catalog is not None:
        app.state.observation_binding_catalog = catalog
    return app, sink


def main(argv: list[str] | None = None) -> int:
    """Run the real-MR Web observation console.

    Production composition resolves the explicit PRODUCTION default from the
    upstream BindingRegistry reader and composes the app from those resolved
    sources (``compose_ow_app``). ``--db-dir`` is an
    EXPLICIT-SOURCE compat mode for tests/dev: it bypasses discovery and
    carries no ontology or readiness authority.
    """
    parser = argparse.ArgumentParser(
        prog="python -m observation_window.web.runtime",
        description="Real-runtime Web observation console — reads live MR SQLite backends.",
    )
    parser.add_argument(
        "--db-dir",
        default=None,
        help=(
            "EXPLICIT-SOURCE compat mode (tests/dev): bind to this directory's "
            "cognition_state.sqlite / facts.sqlite, bypassing binding discovery"
        ),
    )
    parser.add_argument(
        "--runtime-dir",
        default=None,
        help="Binding anchor dir (defaults to the compat adapter's production runtime dir)",
    )
    parser.add_argument(
        "--persona-id",
        default=None,
        help="Explicit persona authority for binding discovery (compat default: kayla_v0)",
    )
    parser.add_argument(
        "--binding-ref",
        default=None,
        help="Explicit binding reference file (same chain as MR_RUNTIME_BINDING)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind host (default 127.0.0.1, not 0.0.0.0 — local access only)",
    )
    parser.add_argument(
        "--port", default=8765, type=int,
        help="HTTP port (default 8765)",
    )
    parser.add_argument(
        "--maxlen", default=200, type=int,
        help="Live-trace ring-buffer size (default 200 turns)",
    )
    args = parser.parse_args(argv)

    if args.db_dir is not None:
        print("EXPLICIT-SOURCE compat composition (no binding discovery)")
        app, sink = build_ow_app_from_db_dir(
            db_dir=args.db_dir,
            maxlen=args.maxlen,
        )
    else:
        try:
            from mind_runtime.binding_registry_composition import (
                open_production_binding_registry_reader,
            )
            from observation_window.binding import (
                ObservationBindingCatalog,
                ProductionObservationBindingResolver,
            )
            from mind_runtime.runtime_binding import RuntimeEnvironment

            reader = open_production_binding_registry_reader()
            live_trace_provider = _default_live_trace_provider()
            anchor = Path(args.runtime_dir) if args.runtime_dir is not None else None
            resolver = ProductionObservationBindingResolver(production_root=anchor)
            catalog = ObservationBindingCatalog(
                reader=reader,
                environment=RuntimeEnvironment.PRODUCTION,
                resolver=resolver,
                live_trace_provider=live_trace_provider,
            )
            scoped_default = catalog.resolve_default()
            resolved = scoped_default.resolved_binding
            print("Binding catalog: upstream production registry reader connected")
        except Exception as exc:
            log.error("Production BindingRegistry unavailable; refusing singleton fallback: %s", exc)
            raise RuntimeError(
                "production BindingRegistry is unavailable; refusing legacy singleton fallback"
            ) from exc

        app, sink = compose_ow_app(
            resolved,
            maxlen=args.maxlen,
            live_trace_provider=live_trace_provider,
            catalog=catalog,
        )
        binding = resolved.runtime_binding
        print(f"Binding   : {scoped_default.binding_id} "
              f"(agent={binding.agent_id}, "
              f"env={binding.environment.value})")
        print("Binding-registry composition (explicit production default)")
        print(f"State DB  : {resolved.state_db}")
        print(f"Facts DB  : {resolved.facts_db}")

    print(f"Backend   : SqliteStateBackend + SqliteFactBackend + SqliteCommitMarkerStore")
    print(f"Live cache: maxlen={args.maxlen}")
    print(f"URL       : http://{args.host}:{args.port}")
    print()
    print("READ ONLY — no writes to MR state or facts")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
