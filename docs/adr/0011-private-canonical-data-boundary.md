# ADR-0011: Keep person names in the private shadow corpus; redact only at the export boundary

- **Date:** 2026-08-27
- **Status:** Accepted

## Problem

The D11L shadow pipeline originally coded every person name to
`<person:N>` before writing `shadow.db` (`redact_text(..., KNOWN_NAMES)` on
every event). This broke downstream consumers that need real names:

1. State-extraction rules such as
   `哄(?:<person:\d+>|嘻嘻|她).{0,6}睡` had to guess around tokens, and any
   future rule needing an exact name could never match.
2. The private companion runtime is the canonical cognition consumer of this
   corpus; AGENTS.md §7 (data privacy boundary) explicitly allows the private
   runtime to keep real names, nicknames, and relationships, while requiring
   sanitization only for public release.
3. Uncommitted working-tree work introduced `keep_names=True` (names stored
   plaintext) plus an in-memory `_restore_names()` helper, but the repository
   carried no decision record, and one test still froze the obsolete
   always-redact behavior.

There was no recorded contract saying which boundary redacts what.

## Previous Assumption

Shadow-learned content was treated as if it might be published at any time,
so everything identifying (names and credentials) was coded before storage,
inside the single ingestion pipeline.

## New Evidence

- AGENTS.md §7 already separates "Private Runtime may keep real names" from
  "public release requires separate sanitization"; the ingestion-time name
  coding contradicted the approved policy rather than implementing it.
- Credential-class plaintext (phone/email/id-card/bank-card/PIN-like digits)
  keeps its fail-closed treatment independently of names
  (`shadow/redaction.py`: pattern redaction + `has_sensitive_leak` store
  block). Name coding is not required for credential safety.
- `tests/shadow/test_states.py::test_extract_without_names_keeps_codes_and_no_match`
  failed against working-tree behavior, proving code and tests disagreed
  about which mode is authoritative.

## Decision

1. **Private mode (default):** the shadow store (and any later private
   canonical store) MAY persist person names in plaintext. `run_backfill`
   defaults to `keep_names=True`; only credential-class patterns are tokenized
   before storage, and `has_sensitive_leak` stays fail-closed (a leak refuses
   the write).
2. **Export/publication boundary:** strict `<person:N>` person coding plus a
   full public-release sanitization pass belongs exclusively to a future
   export step (`keep_names=False` parameter path exists for it). That export
   pipeline is NOT yet implemented and remains tracked as a gap; nothing may
   be published through the ingestion pipeline alone.
3. **Extraction is dual-mode:** state rules must match both plaintext names
   and `<person:N>` codes; `_restore_names()` reconstructs names in memory
   for matching only and is never persisted.
4. Reversibility note: `<person:N>` codes are positionally derived from
   `KNOWN_NAMES`, so they were never an anonymity guarantee — formalizing
   them as an export-only transformation removes a false sense of privacy
   without changing actual exposure inside the private runtime.

This decision covers D11 validation/learning infrastructure only. It does not
change kernel contracts (Evidence/Observation/State/Situation/Appraisal/
Intent/Expression semantics are untouched).

## Rejected Alternatives

- **Keep HEAD's always-redact ingestion:** freezes rules to token guessing,
  contradicts AGENTS.md §7, and made the shipped extractor unable to see
  names; rejected because the policy boundary was already approved above.
- **Store a persistent name→code mapping table:** implies reversibility was a
  designed property and encourages exporting with codes as pseudo-anonymity;
  rejected because it adds an identity oracle without adding safety.
- **Defer until MR-4 Memory privacy design:** the shadow daemon runs today
  against live private traffic; ambiguity between code and tests had to close
  now, not after MR-4.

## Affected Contracts

none. No protected category (observation/state/memory semantics, scope/
authority/ownership, replication, TurnProjection, dynamics, appraisal input,
ActionPolicy/ExpressionGuard boundaries, DecisionContext, Intent lifecycle)
is affected. Governance documentation (AGENTS.md §7) already stated the
policy; this ADR records it as the executable boundary.

## Migration

- Existing stores written under always-redact contain `<person:N>` text;
  extraction continues to accept both forms, so no data migration or rebuild
  is required. Old rows are rotated out by the existing 30-day retention.
- Rollback: set `keep_names=False` at the sync/backfill entry points to
  restore HEAD-era ingestion behavior without code changes.

## Acceptance Tests

- `tests/shadow/test_states.py` — dual-mode extraction:
  plaintext names match without arguments
  (`test_extract_matches_plaintext_names`), `<person:N>` codes match even
  with no known names (`test_extract_tolerates_person_codes_without_known_names`),
  and restore aids matching when names are provided
  (`test_extract_matches_coded_corpus_with_known_names`).
- `tests/shadow/test_redaction.py` — credential redaction + fail-closed leak
  gate unchanged and green.
- `tests/shadow/test_sync.py` — end-to-end Hermes→shadow ingestion keeps
  credentials gated and messages idempotent under the new cursor contract.
