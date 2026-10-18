# Development and acceptance

Run commands from the repository root. User installation and the first simulator
example are in the [README](../README.md#installation).

## Local development

After installing the public release as described in the README:

```sh
python -m pip install --requirement requirements/preview-downloads.txt \
  --constraint requirements/preview-constraints.txt -e '.[simulator,dev]'
python -m pytest -q
```

Tests are grouped by [module ownership and integration scope](../tests/README.md).
Full runtime validation is a local acceptance step. This repository has no GitHub
Actions workflows; GitHub stores source and prebuilt release assets.

## Protocol acceptance

The fixed suite covers PCR, OT-2 bead washing and Flex bead washing, each with
normal completion, pre-execution rejection and unknown outcomes.
It retains input snapshots, run and station stores, logs, JUnit and `summary.json`.
Missing, skipped or failed required cases fail the gate.

```sh
python -m tests.acceptance.protocols \
  --output-dir run-artifacts/protocol-acceptance/first-run
```

Use a new output directory. [Manifest](../design/protocol-acceptance-suite.json)
· [Recorded evidence](evidence/protocol-acceptance-20261018.json).

## Resident acceptance

The unified suite covers fixed program profiles, mixed protocols, Flex position
continuity, cancellation, unknown outcomes, restart and architecture.

```sh
python -m tests.acceptance.resident \
  --output-dir run-artifacts/resident-acceptance/first-run
```

Use a new output directory. [Manifest](../design/resident-acceptance-suite.json)
· [Recorded evidence](evidence/mixed-resident-protocols-20261018.json).

Different complete programs share the [fixed station](../examples/resident-station/deck.json)
through [program bindings and routes](../examples/resident-station/workspaces.json):

```sh
# Terminal 1
culsma-os serve --station-id pcr-beads --socket /tmp/culsma-mixed.sock \
  --host-db run-artifacts/resident-station/os.sqlite3 \
  --driver-config examples/resident-station/deck.json \
  --workspace-config examples/resident-station/workspaces.json \
  --artifacts-dir run-artifacts/resident-station
# Terminal 2: first wait for status "ready".
culsma-os host-status --socket /tmp/culsma-mixed.sock
```

Once ready:

```sh
culsma-os submit examples/pcr-benchmark/protocol.culs --socket /tmp/culsma-mixed.sock
culsma-os submit examples/magnetic-buffer-exchange/protocol.culs --socket /tmp/culsma-mixed.sock
```

Station resources continue between jobs; simulated material inputs are independent
per run. Checkpoints retain compiled plans and configuration snapshots. Restart
requires matching station and service configuration; it does not reload source.
Changing an artifact directory does not reset station state, and editing a
configuration does not authorize moving hardware or resetting recorded positions.

## Build checks

```sh
python -m pip install -r requirements/build.txt
python tools/check_public_tree.py
python -m pytest tests/architecture/test_distribution.py \
  tests/architecture/test_preview_artifacts.py \
  tests/architecture/test_dependency_bundle.py \
  tests/architecture/test_public_text.py -q
python -m build --no-isolation
python tools/check_distribution.py --directory dist
```

Build and verify artifacts locally before uploading a release.

## Design contracts

- [Runtime baseline](../design/framework-baseline.json)
- [Station state ownership](evidence/station-workspace-20261017.json)
- [Program workspace bindings](../design/program-workspace-contract.json)
- [Resident acceptance contract](../design/resident-protocol-acceptance.json)
- [Distribution and exact dependency snapshots](../design/distribution-contract.json)
- [Public preview preparation](../design/public-preview-contract.json)
