# Offline historical tools

This directory is outside the installed Mind Runtime package. Online Body does
not import it. MR-Mem is a tool dependency, not a new online provider dependency.

The normative boundary is
[Hot-Start Source Curation](../docs/architecture/MR_HOT_START_SOURCE_CURATION_FROZEN_INVARIANT.md).

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
