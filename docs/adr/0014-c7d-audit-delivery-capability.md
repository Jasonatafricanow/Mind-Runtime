# ADR-0014: C7D-AUDIT — Delivery Capability Level and Host Adapter Gap

- **Date:** 2026-08-31
- **Status:** Blocked (SOURCE_MISSING) — C7D-SOURCE executed; no carrier source found in repo or host config; C7D-AUDIT thread STOPs; see STOP directive below

> **C7D-AUDIT = BLOCKED.** MR's own delivery orchestration is fully characterised
> (LEVEL 0, durable, privacy-honoured). However, no Telegram / Weixin / Hermes
> send implementation exists anywhere in the codebase. Without a real carrier source,
> the idempotency capability of Telegram or Weixin cannot be classified. The
> C7D-AUDIT is complete; the next step is C7D-SOURCE.

## Problem

The Mind Runtime delivery plane (C7A + C7B) has two independent capability surfaces that are easy to conflate:

1. The **Hermes / shadow ingestion path** — read-side only, pulls chat history from a local SQLite file at `~/.hermes/`.
2. The **C7 delivery plane** — durable outbound request queue + state machine + kill switch + restart daemon.

Neither surface has a real Telegram, Weixin, or WeChat send implementation. An auditor needs a single document that:

- Enumerates every API reference to these platforms in the codebase and what each reference actually does.
- Determines the current idempotency capability level of the delivery plane.
- Proposes a minimal `DeliveryPort` adapter interface for whichever provider is chosen.
- Confirms dry-run mode, the privacy posture, and safety properties of the kill switch.

## Previous Assumption

C7A / C7B were reviewed with the assumption that "Hermes" referred to the production shadow source, which was implicitly a "real" external system. The C7 delivery plane's `DeliveryPort` Protocol was treated as a concrete capability even though zero implementations exist.

## New Evidence

### C7D-AUDIT-1: Hermes / Telegram / Weixin / WeChat API inventory

| Reference | File | Lines | What it actually does | Real / Stub |
|---|---|---|---|---|
| `HermesMessageSource` | `src/mind_runtime/shadow/sources/hermes.py:59` | 59–109 | **Read-only** adapter over `~/.hermes/profiles/xiyue/state.db`; JOINs `messages` + `sessions`; filters cron/webhook/subagent. No send path. | Real (read-side) |
| `HermesProductionBridge` | `src/mind_runtime/shadow/source_bridge.py:162` | 162–346 | Adapts Hermes/shadow records into `SourceRecord` objects; drives canonical lifecycle. Read-side only. | Real (read-side) |
| `HermesEvent`, `HermesPage` | `src/mind_runtime/shadow/sources/hermes.py:38, 46` | 38–55 | Row-mapping dataclasses for Hermes SQLite rows. | Real (read-side) |
| `Channel.TELEGRAM`, `Channel.WEIXIN` | `src/mind_runtime/shadow/classifier.py:16–17` | 16–17 | Classification vocabulary only — no transport. | Real (enum) |
| `HermesProductionBridge` (daemon) | `src/mind_runtime/shadow/daemon.py:1` | 1–215 | Long-running sync daemon; gates on `MIND_RUNTIME_PRODUCTION_INGEST` and `MIND_RUNTIME_PROACTIVE_TICK`. Calls `sync.py` and `runtime_loop.py` subprocesses. | Real (read-side daemon) |
| Shadow backfill | `src/mind_runtime/shadow/backfill.py:22, 61` | 22, 61 | `HermesMessageSource.fetch_page()` into shadow store. | Real (read-side) |
| Shadow runtime loop | `src/mind_runtime/shadow/runtime_loop.py:5, 9, 17` | 5–510 | Production STEP 1–10; `HermesProductionBridge` in LIVE mode. | Real (read-side) |
| DeliveryPort Protocol | `src/mind_runtime/delivery/__init__.py:138` | 138–148 | `deliver(request) -> DeliveryReceipt`. Protocol only; zero concrete implementations in the repo. | Stub (Protocol) |
| InMemoryDeliveryBackend | `src/mind_runtime/delivery/__init__.py:252` | 252–300 | Deterministic in-process fake carrier used in tests. Explicitly documented as "NOT production restart authority." | Stub |
| SqliteDeliveryBackend | `src/mind_runtime/delivery/persistence.py:499` | 499–925 | **Real** local durable queue and state machine. The on-disk SQLite file is the only source of truth across restarts for the delivery plane. | Real (durable local queue) |
| Orchestrator `DeliveryStatus` synthesis | `src/mind_runtime/pipeline/orchestrator.py:769–784` | 769–784 | The orchestrator synthesises SENT / UNSENT `DeliveryStatus` from `ExpressionDisposition.ACCEPT` — a local expression outcome, not a network call. | Stub (synthetic) |
| `real_body_agent.py` | `src/mind_runtime/memory/real_body_agent.py:35` | 35–146 | Real LLM call adapter (Gemini native or OpenAI-compatible). Calls a chat endpoint to *generate* Body text. Does NOT send anything to the user. | Real (LLM call) |

**Conclusion:** No real Telegram / Weixin / WeChat send API is implemented anywhere in the codebase. The words "telegram", "weixin", and "wechat" appear exclusively in the read-side shadow ingestion path and in classification enums.

### C7D-AUDIT-2: Idempotency capability level

The C7B idempotency level framework is defined at `src/mind_runtime/delivery/__init__.py:15–43`:

| Level | Description | Current state |
|---|---|---|
| **LEVEL 0** (default) | No provider-side authority. `NoopDeliveryReconciler` always returns `ResolvedUnknown`. UNKNOWN stays UNKNOWN. Orchestrator MUST NOT blind-resend. | **Active.** `SqliteDeliveryBackend` is pinned to LEVEL 0 by default. |
| LEVEL 1 | Provider lookup. Reconciler can ask the provider what really happened and resolve UNKNOWN. | Not implemented. Provider `DeliveryPort` not wired. |
| LEVEL 2 | Provider callback / push delivery. Same as LEVEL 1 plus provider can push ACCEPTED state directly. | Not implemented. |
| LEVEL 3 | Provider explicit idempotency-key APIs. | Reserved; not implemented. |

**Mind Runtime local delivery capability: LEVEL 0 (local idempotency only).** The system guarantees at-most-once delivery at the local durable-queue level and forbids blind resend. It does NOT guarantee exactly-once external delivery unless a LEVEL 1+ adapter is plugged in.

> **Important: LEVEL 0 describes the currently implemented Mind Runtime delivery boundary in absence of a carrier adapter; it is not a capability classification of Telegram, Weixin, Hermes, or any other external provider.** The provider's own send API, message_id semantics, retry/reconcile behaviour, and idempotency-key protocol have NOT entered the evidence chain. Provider capability classification requires C7D-SOURCE to first locate the real carrier source, and a subsequent carrier-specific audit.

### C7D-AUDIT-3: Minimal DeliveryPort adapter interface proposal

The `DeliveryPort` Protocol (`src/mind_runtime/delivery/__init__.py:138`) defines:

```python
def deliver(request: DeliveryRequest) -> DeliveryReceipt:
    """One delivery attempt. MUST NOT raise."""
```

A production host adapter must:

1. Accept `DeliveryRequest` (immutable, `request_id` is idempotency key, `payload_bytes` is the wire form).
2. Return `DeliveryReceipt` — never raise. Translate errors into the contract:
   - **Known provider outcomes** (success, permanent rejection, rate limit, etc.) → map directly to `DeliveryStatus.SENT` / `DeliveryStatus.REJECTED`.
   - **Ambiguous transport outcome** (timeout, connection error, 5xx without a clear result) → `DeliveryStatus.UNKNOWN`. This is the only case where the reconciler is consulted.
   - **Programming error, contract corruption, or invalid internal state** (e.g. wrong payload shape, missing credential, asserted invariant violated) → **raise**. Translating these to `FAILED_RETRYABLE` or `UNKNOWN` would mask internal bugs and cause the daemon to retry indefinitely on a non-retryable error.
3. Map the carrier's error responses to `DeliveryStatus` enum: `SENT` on success, `UNKNOWN` on transient ambiguity, `REJECTED` on permanent rejection.

No changes to the Protocol are required. The host must supply the adapter at runtime via the `SqliteDeliveryBackend` constructor:

```python
backend = SqliteDeliveryBackend(
    db_path=Path("~/.mind_runtime/delivery.db"),
    port=MyTelegramDeliveryPort(api_token="..."),  # <-- host-supplied
    reconciler=NoopDeliveryReconciler(),          # LEVEL 0
)
```

The adapter is the host's responsibility. The Mind Runtime owns the queue, the state machine, the kill switch, and the daemon recovery pass.

### C7D-AUDIT-4: Dry-run, privacy, and safety review

**Dry-run mode:** Not implemented. The `InMemoryDeliveryBackend` with `fail_after=N` simulates a kill switch — it accepts `N` requests then returns `UNKNOWN` for the rest. This is test infrastructure, not a production dry-run flag. A production dry-run would require:
- A `DryRunDeliveryPort` that records all `deliver()` calls without sending, and
- A `DRY_RUN=True` environment variable that the host uses to swap in `DryRunDeliveryPort` at startup.

**Privacy:** The C7B privacy contract (`src/mind_runtime/delivery/__init__.py:45`) requires that the generic daemon log must not expose `request.payload_bytes`. `DaemonOutcome` (`src/mind_runtime/delivery/daemon.py:48`) carries only `request_id`, `decision_kind`, `final_state`, `attempt`, `reason_code`, and `provider_receipt_ref`. No payload content. **Privacy contract: honoured.**

**Kill switch safety:** `DeliveryKillSwitch` (`src/mind_runtime/delivery/kill_switch.py:142`) is:
- Durable (persisted in SQLite, survives restart).
- Fail-closed (default `ON`, never defaults to `OFF`).
- Fine-grained (per-channel and per-target overrides).
- Checked before every `port.deliver()` call in the daemon pass.

**Body egress:** `RealLLMBodyAgent` (`src/mind_runtime/memory/real_body_agent.py`) uses `UrllibChatTransport` with SSRF guard (`validate_egress_url`). It does NOT route through `OpenAICompatibleProvider`. It does NOT send anything to the user. **Body egress posture: isolated from delivery plane.**

**Hermes shadow read:** All Hermes reads are from a local SQLite file at `~/.hermes/`. No network call is made. The read path is gated by `MIND_RUNTIME_SHADOW_ENABLED`. **Shadow read posture: local file only, no external egress.**

## Decision

1. **Mind Runtime local delivery capability: LEVEL 0.** The system guarantees at-most-once delivery at the local durable-queue level. Exactly-once delivery requires a LEVEL 1+ carrier adapter (see C7D-SOURCE finding).

2. **Hermes / shadow is read-only.** The production carrier adapter for outbound delivery is a separate implementation that the host owns and supplies via the `DeliveryPort` Protocol.

3. **No Telegram / Weixin / WeChat send API exists in this repository.** The `DeliveryPort` Protocol is the integration surface. No adapter is provided.

4. **Privacy and kill switch contracts are honoured** in all production paths.

5. **C7D-SOURCE finding: SOURCE_MISSING.** No carrier source is present in the repo or in any host-config files this agent is allowed to inspect. The audit thread STOPs. See the STOP directive below.

6. **Next step: external.** A human or a human-supervised agent must locate the real carrier source and issue C7D-IMPL against it. Do not fabricate substitutes.

## Rejected Alternatives

1. **"Implement a Telegram adapter now."** Rejected. The adapter is host-specific (API credentials, rate limits, polling vs webhook, channel-specific error handling). It belongs with the host, not in MR. MR cannot implement a carrier adapter without first knowing the real carrier source (see C7D-SOURCE).

2. **"Implement a dry-run flag in SqliteDeliveryBackend."** Rejected. The dry-run behaviour is the host's concern (e.g. capture what would have been sent without consuming carrier quota). MR already provides `InMemoryDeliveryBackend` for test simulation.

3. **"Raise capability to LEVEL 1 automatically."** Rejected. LEVEL 1 requires a provider-specific reconciler that can ask the carrier "did this message get delivered?" No such reconciler exists generically. The capability classification of any specific provider is a separate audit step that requires C7D-SOURCE to complete first.

## Affected Contracts

- `DeliveryPort` Protocol — unchanged; the Protocol is the correct integration surface.
- `SqliteDeliveryBackend` constructor — unchanged; `port` argument is already accepted.
- `DeliveryLifecycleState` machine — unchanged; carrier errors must still map to the existing states.
- `KillSwitchDecision` — unchanged; per-channel/target blocks are respected before every `port.deliver()` call.
- No changes to any existing contract type.

## Migration

No migration needed. This ADR documents the current state and future path. Existing code is unaffected.

## C7D-SOURCE finding (executed 2026-08-31)

C7D-AUDIT is blocked until C7D-SOURCE can supply the real carrier source. C7D-SOURCE was executed as a bounded search of:

1. Source code, tests, and pyproject config (this repo).
2. `docs/`, including legacy and audit directories.
3. `.env`, `docker-compose`, and any host-config files in the project tree.

The search covered Telegram, Weixin, WeChat, WhatsApp, email, webhook, carrier, and send-endpoint references. The results:

- **No concrete send API for any carrier exists in the repo.** `DeliveryPort` is a Protocol with zero concrete implementations.
- **No credentials, endpoints, or host adapter code are present.** No `.env` example mentions a Telegram bot token, WeChat app ID, SMTP host, or webhook URL.
- **All "telegram" / "weixin" / "wechat" references are read-side only:** `Channel.TELEGRAM` / `Channel.WEIXIN` classification enums, Hermes ingestion, test fixture channel labels. None of them send.
- **Hermes itself is read-only.** `HermesMessageSource` reads from `~/.hermes/profiles/xiyue/state.db`; there is no Hermes outbound carrier.
- **Legacy notes** (`docs/legacy/kayla-rule-map.md`) reference `telegram-bridge/bridge.js` at an external host path; that file is outside the repository and was not examined by C7D-SOURCE.
- **Audit-level gap docs** (`docs/docs/MindRuntime_C0_Recon_Report.md`) explicitly flag "Outbound DeliveryPort + real transport adapters (Telegram/WeChat/Hermes outbound)" as a gap.

**Outcome: SOURCE_MISSING.** No carrier source is available in this repository or in the host-environment files C7D-SOURCE is allowed to inspect.

## STOP directive (2026-08-31, post-C7D-SOURCE)

Following the user's directive ("do not fabricate"):

- **No `Host Delivery SPI` will be invented.** SPI design is downstream of source identification.
- **No Telegram/Weixin/Hermes adapter will be implemented.** Without a real source to integrate against, any implementation would be a substitute, not a wrapper.
- **No dry-run flag is added to `SqliteDeliveryBackend`.** Dry-run is a host concern; the test-only `InMemoryDeliveryBackend` already serves as the simulation surface.
- **No capability upgrade to LEVEL 1+.** LEVEL 1 requires a provider-specific reconciler, and no provider is in scope.

The C7D-AUDIT thread **stops here**. The next step is **external**: a human or a human-supervised agent must locate the real carrier source (inside the connected local projects, or via the user's local source tree, or via a separate clone of the carrier library), then issue C7D-IMPL against that real source.

## Branch / merge strategy

- **C7A → C7C-R3** is a complete, audited MR capability. It does not require a real carrier source to be useful: `SqliteDeliveryBackend` provides durable at-most-once delivery with the kill switch, lifecycle state machine, and restart daemon, all proven against the existing test surface. These slices can merge to `main` independent of any carrier implementation.
- **C7D-AUDIT (this ADR)** is BLOCKED on C7D-SOURCE. The audit findings are durable: LEVEL 0 classification with the scope disclaimer, the tightened adapter error contract, the privacy / kill switch review.
- **C7D-SOURCE** has been executed and returned **SOURCE_MISSING**. ADR-0014 records the search and the finding.
- **C7D implementation** (thin carrier adapter, dry-run, controlled real-send cert) is a separate branch, owned by the host-adapter work, and **does not block the C7A → C7C-R3 merge to main**.

> main can hold: "MR has a durable delivery protocol; the current reference deployment has no real carrier adapter wired." That is a deployable statement, not an unfinished C7.

## Acceptance Tests

The acceptance criteria for this ADR are:

1. [x] C7D-AUDIT-1 inventory compiled — all Hermes/Telegram/Weixin/WeChat references catalogued and classified as read-side or absent.
2. [x] C7D-AUDIT-2 capability level confirmed as LEVEL 0 with explicit scope disclaimer (MR local boundary only; not provider classification).
3. [x] C7D-AUDIT-3 adapter interface documented with tightened error-handling contract (programming errors → raise; ambiguous → UNKNOWN; known → map directly).
4. [x] C7D-AUDIT-4 privacy + kill switch review completed — all production paths honour payload non-disclosure and fail-closed defaults.
5. [x] ADR written and accepted.
6. [x] ADR status updated to BLOCKED — real carrier source not found; next step is C7D-SOURCE task.
7. [x] C7D-SOURCE executed (bounded repo + host-config search) — returned SOURCE_MISSING. All references to carriers are read-side or absent; no credentials, endpoints, or adapter code present.
8. [x] STOP directive issued — no Host Delivery SPI invented, no adapter fabricated, C7D-AUDIT thread closed pending external source location.
