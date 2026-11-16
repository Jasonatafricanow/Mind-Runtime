# Integration note — Always-on Host / WorkBench / MR / MR-Mem separation

- Date: 2026-11-16
- Status: **PROPOSED / non-normative integration clarification**; the accepted
  [MR architecture lock](../architecture/MR_ARCHITECTURE_LOCK_v1_1.md)
  remains authoritative.
- External design reference: [Anthropic, Building always-on agents
  (2026-11-13)](https://claude.com/resources/articles/building-always-on-agents).
- Consumer: [Agent-WorkBench](https://github.com/Jasonatafricanow/Agent-WorkBench),
  feature branch `feat/modular-backend-20261116`.

## Distinct clocks and authority

| Concern | Owning system | MR's responsibility |
|---|---|---|
| User asks for a deliverable; task is WAITING | WorkBench SQL task event/dependency | Optional bounded interpretation; not business task truth |
| Scheduled business check-in / official deadline | WorkBench business timer and durable wake inbox | None of the business deadline enforcement |
| Session, Run, tool call and deferred resume | Existing Body/Agent Host | Can supply DecisionContext / cognitive WakeSignal; does not execute |
| Cognitive proactivity over elapsed time | MR Soul internal intent and wake semantics | Remains MR authority; may request Host activation, never bypasses Host |
| Source-grounded semantic history | MR-Mem sidecar canonical + Thread/LCE | Optional evidence-backed context; no task/Run status ownership |
| External Telegram send and its receipt | WorkBench outbox + Host/carrier | Operational delivery handoff may be observed; not experiential evidence |
| Real user/environment response | External evidence via perception boundary | Can become experiential input through existing admission/appraisal rules |

Always-on UX is an event-driven sequence of short Host runs, not perpetual
LLM inference and not a perpetual MR tool-execution loop.

## Protocol implications

1. WorkBench normalizes authenticated inbound messages, timers, GitHub changes
   and approved decisions into durable business events.
2. WorkBench sends an **idempotent event reference** to the existing Host;
   only Host chooses whether to create/resume a Session and runs the tools.
3. MR can provide bounded cognition, intent tendency or WakeSignal under
   existing runtime binding; **no authority escalation** from MR output
   to Host tool permission.
4. Host returns operational acknowledgements with opaque Run/Session refs.
   WorkBench may correlate these to tasks but **must not own Host checkpoints**.
5. For deferred tool calls, Host owns saved call/session and execution
   authorization. WorkBench owns the approver, pending business decision,
   deadline and notification. A verified reply is a new event to Host.
6. Host checks current tool permission and scope again *at resume time*.
7. WorkBench task completion requires business evidence; a completed
   Host Run, message send receipt or internal ShadowRun is insufficient.
8. MR-Mem accepts only eligible host-accepted semantics with exact
   `SourceRef`; operational receipts alone are not new user preference,
   emotion, relationship or commitment evidence.

## Naming safeguards

- `Mind WakeSignal`: a cognitive desire/signal; not a WorkBench timer.
- `WorkBench wake_event`: a business event ready for Host dispatch;
  not an MR cognition update.
- `Host Run`: the executing session/run; **not** a WorkBench task.
- `MR delivery/intent records`: Soul-to-Body handoff/retry accounting.
- `WorkBench delivery_outbox`: business notifications and their delivery
  reconciliation; not a new MR carrier.
- `MR Observation Window`: read-only MR state inspection; not the
  WorkBench dashboard nor a path to write MR state.

## Required negative tests at system integration

- WorkBench task WAITING persists when Host Run finished or process died.
- MR WakeSignal cannot cause an unauthorized Host tool call.
- Revoked approval cannot resume a deferred tool call.
- Host Run finished does not auto-complete the linked task.
- Delivery receipt does not strengthen cognition or relationship state.
- MR-Mem indexing lags without degrading SQL current task truth.
- Agent Host failure does not lose pending business events.
- Duplicate source event does not produce duplicate external action;
  unknown outcomes are reconciled, not blindly retried.

## Scope and implementation status

This note does not introduce a planner, Host loop, transport driver, new
permission system, or generic workflow scheduler into MR. No MR code changes
are proposed. Integration functions belong in WorkBench and Host adapters,
respecting the current MR architecture freeze and review/change-control
requirements. The above negative tests are **not** claimed to have passed
against a live multi-service deployment.
