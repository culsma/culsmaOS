# Development and acceptance

Run commands from the repository root. User installation and the first simulator
example are in the [README](../README.md#installation).

## Repository layout

| Location | Purpose |
| --- | --- |
| `diagrams/` | Compact public architecture overview |
| `docs/reference/` | Current architecture ownership and supported capability scope |
| `tests/acceptance/manifests/`, `tests/architecture/module-map.json` | Executable acceptance and source-component checks |
| `tools/distribution/manifest.json` | Exact dependency artifacts used by build and verification tools |

Detailed design diagrams and diagram consistency checks are maintained in a separate
internal workspace. Public acceptance is self-contained and checks source boundaries.

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

Use a new output directory. [Manifest](../tests/acceptance/manifests/protocols.json).

## Resident acceptance

The unified suite covers fixed program profiles, mixed protocols, Flex position
continuity, cancellation, unknown outcomes, restart and architecture.

```sh
python -m tests.acceptance.resident \
  --output-dir run-artifacts/resident-acceptance/first-run
```

Use a new output directory. [Manifest](../tests/acceptance/manifests/resident.json).

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

## Station console (development checkout)

This console is under development and is not part of the published 0.1.1 wheel.
Install this checkout using the local development command above. Start an existing
resident service, then attach the console from another terminal:

```sh
# Terminal 1
culsma-os serve --socket /tmp/culsma-console.sock \
  --host-db run-artifacts/console/os.sqlite3 \
  --driver-config examples/transfer/deck.json \
  --artifacts-dir run-artifacts/console
# Terminal 2
culsma-os console --socket /tmp/culsma-console.sock --port 8765
```

Open the printed loopback URL. Station, run list and run detail display OS records;
the execution views cannot submit work or change resources. A fresh service can have no
device records until its first accepted run. Submit through the existing CLI:

```sh
culsma-os host-status --socket /tmp/culsma-console.sock
# Wait for ready, then:
culsma-os submit examples/transfer/transfer.culs --socket /tmp/culsma-console.sock
```

Stopping the console does not stop the resident service. An unavailable host is
shown as disconnected; the console never starts or resumes execution implicitly.

Run detail also reads a separate run-scoped evidence view. Expand intent, execution
and registration records to inspect their identities and payloads. Device attempts
and no-action logical completions are separate; derived collective evidence keeps
its coverage label. Missing receipts and unmatched registrations stay explicit.
Evidence and registration share one read snapshot; the run summary is independent.
The view does not claim hardware timing or include every semantic declaration.

### Configuration drafts

Open **Configuration**, choose an installed profile and use **New from profile**
or import a device configuration JSON file. Edit fields, save a draft, validate
its saved revision and export the validated JSON. Labware and binding forms are
structured; modules, routes and policy remain available through Advanced JSON.
Validation uses the external driver's optional offline profile capability and
installed labware definitions. It is not program preflight or a hardware check.

Drafts default to `run-artifacts/console/drafts.sqlite3`; select a different local
store with `--drafts-db PATH`. Saving/exporting never activates configuration or
changes recorded tips, positions or reservations. Use an exported file explicitly
when starting `serve`; existing configuration and ownership guards still apply.

Writable draft requests use an ephemeral same-origin, console-process credential.
It expires when the console restarts and grants no execution-control capability.
This is a single-user loopback console, not a multi-user login system. The external
driver must provide `configuration_profile()`; older plugins remain usable for
execution inspection but cannot validate/export configuration drafts.
