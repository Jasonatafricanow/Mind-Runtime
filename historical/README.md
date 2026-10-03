# Offline historical tools

This directory is outside the installed Mind Runtime package. Online Body does
not import it. MR-Mem is a tool dependency, not a new online provider dependency.

The normative boundary is
[Hot-Start Source Curation](../docs/architecture/MR_HOT_START_SOURCE_CURATION_FROZEN_INVARIANT.md).
The [Semantic Executor Boundary](../docs/architecture/MR_SEMANTIC_EXECUTOR_BOUNDARY_V1.md)
freezes the separate online and offline executors and shared canonical protocol.

`HistoricalSourceIterator` reads Hermes `sessions/messages` through a read-only
SQLite connection, scoped to an explicit native owner and namespace. Native
timestamp and row ID define ordering; a fingerprint covers the source revision.
It binds historical interaction identity independently of agent output.

`HistoricalSourceCurator` uses role and operational provenance to classify
COMPILE, CONTEXT_ONLY, or IGNORE. Short USER replies remain candidates. Only
COMPILE records may obtain a semantic admission binding. No Raw is copied into
MR Evidence/Observation records, and no historical source is rewritten.

Run from the repository root with MR-Mem installed:

```sh
python -m pytest historical/tests -q
python -m ruff check historical
```

## External worker and rebuild

`ExternalAGYAdapter` launches a replaceable one-shot command with the historical
prompt on stdin. Its argv must include exactly one `{output}` placeholder for
the final JSON file. stdout/stderr are audit only. The wire guide is derived
from installed MR-Mem types, and only MR-Mem parses/validates/adopts the proposal.
An example command is `codex -a never exec --ephemeral --sandbox read-only
--skip-git-repo-check --output-last-message {output} -`.

Run `python -m historical --help` from a tool workspace. Required arguments are
`--raw-db`, `--owner`, `--namespace`, `--rebuild-root`, and
`--worker-command-json` (a JSON argv array). `--selection-file` is a JSON mapping
from native record ID to `context_record_ids` and `activated_memory_ids`.
Only earlier context records in the same session and active canonical Blocks
in the same scope are eligible. An empty selection supplies no extra history.

The rebuild root must be a fresh directory. It contains an independent
`historical-rebuild-v1.sqlite`, an OS process lock, and atomic `checkpoint.json`.
Existing roots require `--resume`; a production DB path, symlink, changed Raw,
scope, namespace, schema or prompt is rejected. Raw is read-only. No affect
runtime, online Body lifecycle, legacy factual admission or cutover is run.

Historical admission binds `known_at` to the current source's original native
message timestamp (`SourceRef.occurred_at`), not the rebuild wall clock. Each
source has its own binding; receipt recovery preserves the frozen historical
timestamp and identity. Online admission clock behavior is unchanged.

`--limit` checkpoints a batch. On restart the iterator resumes after the native
ordering key. A saved proposal is reused; an accepted MR-Mem transaction/receipt
is recovered before any external worker call. Counts are per source disposition;
`defer_count` counts fully deferred sources. Failure keeps the pending source and
cursor, blocking later sources. Replace the workspace to intentionally restart
after a rejected immutable proposal; do not overwrite checkpoint authority.
