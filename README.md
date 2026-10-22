# Mind Runtime

[English](README.md) | [简体中文](README.zh-CN.md)

A persistent state runtime for long-lived agents. It separates evidence admission, committed state and read-only observation so an agent can recover from stored state after restart.

## What is implemented

- Persistent facts, identity/runtime bindings and commit/abort boundaries.
- Restart recovery and deterministic certification fixtures.
- Read-only Observation Window.
- Memory retrieval and optional LCE integration with source validation before context admission.

## Install and verify

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

The public CI also uses coverage, Ruff and mypy no-regression gates. [Implementation and verification details](docs/IMPLEMENTATION.md) · [architecture authority](AGENTS.md) · [project history](PROJECT-HISTORY.md).

## Current research context

The standalone [MR-Mem](https://github.com/Jasonatafricanow/MR-Mem) repository develops semantic memory and derived cognition as a sidecar to host-native history. This README describes this repository's committed runtime; newer designs in another repository do not automatically describe this checkout.

Try the [host commit and process-restart example](examples/README.md) to see durable replay prevention in two separate processes. Live shadow validation and a current Observation Window screenshot remain incomplete; the historical D7–D11 gate vocabulary stays in research records.

## Rights

No project-wide reuse license has been selected. All rights remain with their respective holders; public source visibility does not grant an open-source license. See [NOTICE.md](NOTICE.md).
