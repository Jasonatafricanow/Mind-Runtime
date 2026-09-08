# Optional MR to LCE binding

The adapter implements LCE Core V0's existing `MemorySubstratePort`. MR owns
all canonical Memory reads; LCE owns only its independent Baseline revisions.
See ADR-0026. Default production composition does not import or invoke LCE.

## Install the frozen optional dependency

LCE is not a default MR dependency and is not vendored. In an isolated Python
3.12+ environment, install the verified local Git source at its frozen commit:

```powershell
python -m pip install 'git+file:///C:/projects/LCE@d1eb5f63b427f216df0e38bde48eaff639546391'
```

Adjust the repository location for another host while preserving the exact
revision. Do not substitute an unverified public package with the same name.
Pip's installed `lce-core` distribution `direct_url.json` records the source
commit; verify it before an enabled deployment. No Qdrant, FastEmbed, model
files, embedding SDK, or API key is needed for explicit-ID consolidation.
Missing optional LCE imports raise `LceIntegrationUnavailable` when enabled.

## Explicit composition

The trusted composition owner supplies an existing RuntimeBinding, an
authorized production `Scope`, an explicit tuple of selected MR Memory IDs,
and an implementation of frozen LCE's `SemanticConsolidatorPort`. Scope is
not inferred from the IDs. Do not expose arbitrary caller-selected Scope as
an authentication mechanism.

```python
from mind_runtime.integrations.lce import open_lce_binding

# binding, authorized_scope and consolidator come from trusted composition.
# memory_ids are stable MR IDs; region_id is an opaque LCE lineage ID.
session = open_lce_binding(
    binding, authorized_scope, enabled=True, consolidator=consolidator,
)
assert session is not None
with session:
    result = session.core.consolidate(region_id, memory_ids)
    history = session.core.get_history(region_id)
```

This is an explicitly enabled composition example, not Xiyue activation.
There is no production consolidator selection or automatic discovery policy
in this ticket. In Lab/tests, supply isolated `lab_root` and `production_root`
through the existing Runtime resolver. The integration accepts no Memory DB
path. Binding and Memory storage must already exist; reads never initialize
or claim canonical storage.

`MrMemorySubstrateAdapter(binding, authorized_scope, ...).get_by_ids(ids)` can
also be injected directly into frozen LCE. It accepts 1–100 distinct IDs,
preserves their order, and rejects the entire set if any ID is unknown,
outside the authorized Scope, or not ACTIVE. Duplicate IDs are errors.
No views escape a failed selection and LCE cannot call its consolidator
until selection succeeds. Source refs are canonical Evidence refs. Metadata
is an immutable empty mapping for this explicit-ID seam.

Selection can start with existing `MemoryRetrievalService.search`: take the
resolved objects' `memory.memory_id` values and pass them explicitly. The
adapter still revalidates against canonical SQLite. Provider text, UUIDs,
scores, and embedding coordinates never become content or provenance.

## Independent persistence and restart

The existing Runtime StoragePaths supplies:

```text
<runtime namespace>/memory.sqlite
<runtime namespace>/lce/<sha256(full structured Scope JSON)>/lce_baselines.sqlite
```

Only the latter is written by LCE. Scope partitioning prevents the same
opaque region ID from exposing another Scope's previous Baseline. The path
digest is not a cognitive field or region identity. Reopen the same Runtime
and Scope to reconstruct Baseline head/history. Lifecycle filtering applies
to newly selected Memory; this ticket does not rewrite prior LCE history.

LCE equivalence remains normalized-string equality. No vector equivalence,
supersession emitter, reinforcement, or reverse writeback is introduced.
Removing the derived index prevents semantic discovery but does not prevent
explicit-ID consolidation. Consumers must keep provider outages distinct
from empty retrieval results, as required by MR-MEM-2.

## Verification

Install the frozen LCE package and run `python -m pytest tests/lce_binding -q`.
The optional real Qdrant test uses the existing MR-MEM-3 extra and synthetic
fixture vectors, not an embedding-quality benchmark. With LCE absent, its
integration tests are explicitly skipped; the no-site-packages default-OFF
test still runs. Acceptance evidence must use the frozen package with no
LCE skips. Frozen LCE does not ship a `py.typed` marker, so adapter type
verification uses `mypy --follow-imports=silent --follow-untyped-imports
src/mind_runtime/integrations/lce.py` against its installed source.

## Activation boundary

Memory admission, semantic retrieval, and LCE invocation remain OFF by
default. The MR-MEM-1 fact-commit/job-registration crash gap remains a
PRE-PRODUCTION-ACTIVATION BLOCKER. No historical corpus was processed.
STRUCTURE-06, Hot Start, topology, reverse MR projection, Chinese embedding
quality certification, and research Gemini space remain unchanged.
