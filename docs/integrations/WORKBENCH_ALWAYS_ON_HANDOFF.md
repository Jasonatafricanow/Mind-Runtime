# Integration note — Always-on Host / WorkBench / MR / MR-Mem separation

> Complete design reasoning, topology, cognitive-vs-business wake and status: [WORKBENCH_DESIGN_RATIONALE.md](WORKBENCH_DESIGN_RATIONALE.md).

- Date: 2026-11-16
- Status: **PROPOSED / non-normative integration clarification**; the accepted
  [MR architecture lock](../architecture/MR_ARCHITECTURE_LOCK_v1_1.md)
  remains authoritative.
- External design reference: [Anthropic, Building always-on agents
  (2026-11-13)](https://claude.com/resources/articles/building-always-on-agents).
- Consumer: [Agent-WorkBench](https://github.com/Jasonatafricanow/Agent-WorkBench) (`main`).

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
8. MR-Mem offers the Agent two tools, `write` and `search`. The Agent doing
   the work writes what it understood in that turn, with an exact `SourceRef`
   pointer; there is no memory outbox and no second model re-judging it.
   Operational receipts alone are not new user preference, emotion,
   relationship or commitment evidence, so the Agent does not write them as such.

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

## Human participation and progressive responsibility transfer

Normative WorkBench business contract: [ADR-0003 — Progressive Delegation](https://github.com/Jasonatafricanow/Agent-WorkBench/blob/main/docs/ADR-0003-PROGRESSIVE-DELEGATION.md).

The human is a first-class participant in the WorkBench business loop, not a
mandatory trigger for every Agent Run. WorkBench owns the accountable owner,
current executor, work-class delegation profile, autonomy level, Human Action
Inbox, and auditable transfer/override history. Authorized independent work
continues while the human is offline; genuinely human-dependent work remains
pending with an explicit due/escalation policy.

This is a WorkBench business responsibility, not a new MR scheduler or
permission system. MR can provide cognitive context, relationship-aware
interpretation, intent tendency or a WakeSignal that suggests attention.
It cannot assign a WorkBench executor, promote an autonomy level, approve a
business action, or grant a Host tool capability. The Body/Agent Host still
owns final tool policy and revalidates permission at every call/resume.

MR-Mem may inform how the Agent understands prior experience and preferences,
but it is not the authority for current delegation or consent. A semantic
memory or successful prior Run never changes a WorkBench policy by itself.
Only a current authenticated human decision or a pre-approved, evidence-gated
WorkBench policy may change responsibility. Human override/revocation must
take effect immediately for future dispatch; independent work should not be
blocked by unrelated pending human requests.

The four dimensions remain separate: WorkBench task state, WorkBench
responsibility/autonomy, MR cognitive wake/intent, and Host Run/Session state.

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
