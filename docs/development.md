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
culsma-os console --socket /tmp/culsma-console.sock --port 8765 \
  --program-root examples/transfer
```

Open the printed loopback URL. Station, run list and run detail display OS records;
a fresh service can have no device records until its first accepted run. Use
**Submit program** to select a source, check its snapshot and submit it to this
service. The CLI remains available:

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

Draft and program commands use an ephemeral same-origin, console-process credential.
It expires when the console restarts; draft operations cannot activate configuration.
This is a single-user loopback console, not a multi-user login system. The external
driver must provide `configuration_profile()`; older plugins remain usable for
execution inspection but cannot validate/export configuration drafts.

### Program submission and controls

`--program-root` explicitly enables selection of `.culs` files in that directory.
Checks capture a bounded source/import snapshot; submission executes those reviewed
bytes, even if the original file later changes. Snapshots stay in ignored
`run-artifacts/console/programs` (override with `--program-store`). No upload or
arbitrary browser-selected filesystem paths are accepted.

Source checks cover compilation and supported operations. The resident worker
still checks the running service's device configuration, workspace and resources
before effects. A saved configuration draft is not activated by submission.

Run detail offers pause, resume and cancel at supported boundaries. Acknowledged,
pending, applied and rejected requests remain distinct. A lost response retains
the request ID in browser session storage; retry uses that identity. No action is
automatically retried, and unknown outcomes retain isolation. This development
console supports one local operator; it is not a LAN service or user login system.

### Shared human and browser-agent operation

The same native buttons and labeled inputs support mouse, keyboard and DOM-based
browser agents. Prefer accessible roles/names; stable `data-action`, `data-field`
(JSON pointer), `data-collection` and `data-entity-id` markers disambiguate controls.
The content region exposes the visible page, busy state, saved revision, dirty
state and reviewed snapshot. **Last operation** distinguishes pending requests,
acknowledgements, applied/rejected results and unavailable responses.

These markers describe the page; they grant no authority and expose no credential
or alternate command API. Configuration conflicts retain local edits. The page
cannot identify a human versus an AI that uses the same browser session. MCP uses
a separate process identity and restricted capability; it cannot attest physical
loading. Browser agents sharing the operator session still share that authority.


## Native Hamilton layout export

The optional Hamilton configuration plugin supplies native layout export. Set
`CULSMA_HAMILTON_LABWARE_ROOT` to a local directory containing the matching vendor
labware definitions before starting the console. In Layout, save and check a
Hamilton setup, then choose **Export VENUS layout**. The desktop saves a ZIP in a
new temporary directory and displays its path; copy it elsewhere to retain it.

`export_layout` on the existing configuration endpoint requires the exact saved
revision and returns a driver-owned archive with its configuration fingerprint and
SHA-256. Ordinary configuration JSON export is unchanged. Export does not activate
a station or establish vendor/physical validation. Supported native deck and model
scope is declared by the installed plugin.

Local native E2E, including Hamilton layout export:

```sh
CULSMA_HAMILTON_LABWARE_ROOT=/path/to/Hamilton/Labware \
  python tools/test_desktop.py --with-hamilton
```

## Hamilton loading preparation

The `hamilton-agent` device profile now stops at `awaiting_setup`. Its loading
plan includes automatic or pinned locations, initial contents and one checklist
entry per physical labware. Candidates come from the declared driver layout;
this does not detect loaded stock, invent carrier positions or verify calibration.
Explicit logical-well maps remain required for semantic plates.

```sh
culsma-os setup RUN_ID --socket /tmp/station.sock --action show
culsma-os setup RUN_ID --socket /tmp/station.sock --action begin --fingerprint PLAN_SHA --request-id BEGIN_ID
culsma-os setup RUN_ID --socket /tmp/station.sock --action status --request-id BEGIN_ID
# Place the labware and contents exactly as listed before acknowledging.
culsma-os setup RUN_ID --socket /tmp/station.sock --action confirm --fingerprint PLAN_SHA --acknowledge --request-id CONFIRM_ID
culsma-os setup RUN_ID --socket /tmp/station.sock --action status --request-id CONFIRM_ID
```

Resident mutations return durable request receipts; admission is not application.
`--action revise --preferences '{"fixed":{"ALLOCATION_ID":{"labware":"LABWARE_ID","well":"A1"}}}'`
pins a location. `preferred` uses the same shape with a reported fallback.
Revision invalidates confirmation while preserving the loading reservation.
Operator attestation is recorded separately from sensor evidence. Gun-tip counts
and native parameter bounds still receive driver preparation checks; the checklist
reports declared tip stock, not an independently computed whole-protocol minimum.

For a saved one-shot run, replace `--socket` with `--host-db`, `--driver` and
`--driver-config`; inspect, begin, confirm, then use the existing `resume` command.
Existing preconfigured simulator profiles keep their declared-input workflow.
The run detail's **Prepare and load** card presents this same persisted plan.
Placement selectors support automatic, fixed and preferred addresses; changing a
plan invalidates its confirmation. MCP changes appear through the existing console
polling, with shared request receipts. Unsaved console edits retain their original
fingerprint and require reloading when another client changes the plan.

## External AI through MCP

There is no embedded AI. Start the existing resident normally, then launch the
optional stdio bridge from an **isolated environment** containing the same OS
wheel and language dependency. The MCP SDK and vendor simulator have conflicting
Pydantic/JSON Schema pins; do not combine the `mcp` and `simulator` extras.

```sh
python3.11 -m venv .venv-mcp
.venv-mcp/bin/pip install --find-links /path/to/current-build-wheels 'culsma-os[mcp]'
.venv-mcp/bin/culsma-os mcp --socket /tmp/station.sock \
  --program-root /path/to/programs --program-store /path/to/reviewed-snapshots
```

Configure an external MCP client to launch that command; keep the snapshot store
outside the program root. Both clients must point to the same resident socket.
No device plugin is needed in the bridge environment. The MCP SDK is optional;
normal OS/console installation and simulator operation do not load it.

| Tools | Responsibility |
| --- | --- |
| `station_status`, `list_runs`, `run_status` | Read existing OS observations |
| `list_programs`, `inspect_program`, `submit_program`, `control_run` | Review source snapshots and request queue/control actions |
| `loading_plan`, `revise_loading_plan` | Read or revise the fingerprinted loading plan |
| `begin_loading`, `loading_request_status` | Reserve for loading and inspect durable command outcomes |

There is deliberately no MCP loading-confirmation tool or capability. The operator
loads the listed items, ticks the console acknowledgement and confirms the exact
plan. This is operator attestation, not sensor evidence. Operations are attributed
to the local console or MCP process; these are not multi-user login identities.
Neither transport starts a second runtime or bypasses dispatch/resource gates.

Optional local E2E uses an isolated Chrome profile and a labelled Hamilton backend
double, without contacting an Agent, VENUS or an instrument:

```sh
CULSMA_OS_MCP_SDK_PATH=/path/to/isolated-sdk-packages \
CULSMA_OS_BROWSER_MODULES=/path/to/node_modules \
CULSMA_OS_CHROME=/path/to/chrome \
python -m pytest tests/integration/test_shared_setup_mcp.py \
  tests/integration/test_shared_setup_browser.py -q
```

The browser test uses Playwright Core, PNGJS and Pixelmatch. Reviewed visual
references live under `tests/modules/console/goldens`; generated screenshots and
diffs remain in ignored `run-artifacts/ui-tests`. Reference refresh is explicit
(`CULSMA_OS_CAPTURE_GOLDEN=1`) and requires visual review before replacing a golden.
