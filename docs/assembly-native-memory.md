# Native memory host wiring

Hermes 0.19.0's existing MR seam can now register its durable messages with the
MR-Mem tree pipeline. The host owns raw history. `native_source.sqlite` stores
SourceRefs, versions, job status and accepted compilation, with empty raw-body
columns. Compilation fetches exact current native versions; ownership is checked
against `sessions.user_id`, separately from the logical `MR_USER_ID`.

Use the existing MR patch, then the native addition (both require an explicit
gateway path and reject anchor drift):

```sh
python xiyue/apply_mr_patch.py --apply --gateway-run-py /path/to/hermes/gateway/run.py
python xiyue/apply_native_memory_patch.py --apply --gateway-run-py /path/to/hermes/gateway/run.py
```

The native addition also supports `--check`. It is idempotent for the same checkout.
No live gateway was patched during implementation; the native SQLite adapter and
the rendered patch are tested against repository fixtures.

Set `MR_MEM_NATIVE_ENABLED=true`, `MR_MEM_NATIVE_CONFIG` to an MR-Mem runtime JSON
file, and the existing `MR_MEM_READ_ENABLED`, `MR_MEM_CANONICAL_DB`, `MR_MEM_LINE_ROOT`
and `MR_USER_ID`. The writer's `data_dir/memory.sqlite` and `data_dir/lce_tree` must
match the reader paths. Keep the host database outside `data_dir`.
Use `examples/native-tree.disabled.json` in MR-Mem as a starting configuration.
Native batches require `compile_window=null` and `raw_base=false`. Each batch of
unseen native versions is compiled with prior session context. AML cross-request
windowing remains an AML-specific policy.

Choose either this writer or `SEMANTIC_DELTA_V1_ENABLED`, never both. A source
identity/ownership/configuration error blocks the MR ingress through its existing
failure path. Optional modules are not imported when native ingestion is disabled.

Before MR reads, synchronize the current and previously enrolled sessions. Edits,
deletions and hidden rows invalidate affected canonical support. This also catches
an edit in an older session. Unrelated, never-enrolled sessions are not backfilled.
After a successful MR commit, register new rows and process pending compilation.
The compiler may be `disabled`: report `compiler_not_configured`, persist metadata,
and resume when a compiler is provided. Accepted compilation survives a restart.
Model failure never invokes the conversational Body again. Status is available as
`agent._mr_native_memory_status`; failed compilation is retried on a later commit.
Processing uses the gateway's single-writer lifecycle and an in-process lock.
It does not create a new background daemon; a configured compiler can add commit
latency. Native storage and the sidecar do not form an atomic cross-database snapshot.

An unfinished batch whose source changed is cancelled; its partial admissions are
invalidated before current inputs are queued again. Completed batches retain
unaffected support. Reverting text to an old version creates a new accepted batch
instead of reviving invalidated memory. Current Line reads filter invalidated nodes.

This completes host storage/writer/reader wiring. It does not certify SemanticBlock
boundary correctness, appraisal, or Path B hypothesis algorithms. Path B remains
the second phase explicitly described in MR-Mem's `docs/LCE_DESIGN.md` section 4.8.
Historical context is read under current lifecycle/attention policy; it is not a
complete replay of what every past policy would have exposed.
