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

### Console navigation

The sidebar has three destinations: **Workstation**, **System Settings** and
**System Info**. Workstation combines the existing program selector, source check,
loading plan and confirmation, execution controls, and results in one page. Runs,
history and station resource records are expandable sections. Run URLs select an
experiment inside the same workstation; legacy stage URLs remain accepted. Raw
evidence and completed loading plans are collapsed by default.

The current deck comes from the verified host configuration, including startup
settings without a saved draft. It never substitutes a draft or historical run;
a selected run's preparation shows its own loading plan separately. Layout reads
create no instrument session. Stable view regions preserve deck scroll during
polling. System Settings contains the existing persistent layout editor and
advanced configuration tools; System Info keeps the four read-only information
sections. Navigation does not issue execution commands. File drag-and-drop and
new material or labware editing capabilities are outside this change.

### Configuration drafts

Open **System Settings → Advanced**, choose an installed profile and use **New from profile**
or import a device configuration JSON file. Edit fields, save a draft, validate
its saved revision and export the validated JSON. Labware and binding forms are
structured; modules, routes and policy remain available through Advanced JSON.
Validation uses the external driver's optional offline profile capability and
installed labware definitions. It is not program preflight or a hardware check.

Drafts default to `run-artifacts/console/drafts.sqlite3`; select a different local
store with `--drafts-db PATH`. Saving/exporting never activates configuration or
changes recorded tips, positions or reservations. Apply a validated saved revision explicitly to an idle simulated station, or use
an exported file when starting `serve`. Offline-only profiles cannot be activated;
existing configuration and ownership guards still apply.

Draft and program commands use an ephemeral same-origin, console-process credential.
It expires when the console restarts; saving a draft does not activate it.
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
Its loading diagram groups required labware and supplies by declared carrier,
track or slot. When the driver supplies a layout descriptor, the plan freezes it
and displays the complete deck ruler, carrier footprints and declared sites.
Older plans without geometry retain the location checklist. Select an item to inspect initial contents and explicitly mapped
plate wells. This is a schematic of the required initial placement, not live
physical detection; the operator still confirms the exact plan before execution.
Placement selectors support automatic, fixed and preferred addresses; changing a
plan invalidates its confirmation. MCP changes appear through the existing console
polling, with shared request receipts. Unsaved console edits retain their original
fingerprint and require reloading when another client changes the plan.

## Import an existing instrument layout

In **System Settings → Advanced**, choose the installed profile and select a file
under **Import instrument layout**. Parsing and conversion belong to the driver;
the console only consumes the configuration import report. Import is a preview:
it changes neither the station nor saved drafts. Review diagnostics and retained
objects. The read-only deck preview uses the converted configuration; incomplete
previews omit unrepresented source objects and keep source-coordinate warnings.
Then use an accepted conversion as a new configuration proposal. An
incomplete conversion has no accepted configuration and cannot use that control.
Hamilton imports require matching local definitions. Full instance configurations
retain adjusted coordinates, rotations, stacked objects, sequences and device
records; the console shows a track/carrier/site diagram with stacked objects and
a supplementary fixed-equipment list. Recorded coordinates remain in the object
inspector. Position-based display associations never change execution bindings. Conversion completeness does not grant operation support
for every retained device or establish physical readiness. Configuration JSON is
bounded to 1 MiB; the configuration HTTP routes allow the corresponding envelope.

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
| `list_programs`, `inspect_program`, `preview_program`, `start_program`, `submit_program`, `control_run` | Review source, preview loading without admission, and request queue/control actions |
| `loading_plan`, `revise_loading_plan` | Read or revise the fingerprinted loading plan |
| `begin_loading`, `loading_request_status` | Reserve for loading and inspect durable command outcomes |

Single-clicking a protocol inspects its captured source. Double-clicking or choosing
`Run protocol` performs the offline requirement check and sends one durable `start`
request. The resident records automatic startup in the queue and owns final planning,
reservation and simulation loading. Failures settle through existing run finalization
and are displayed as errors; unknown execution retains isolation. Retrying the same
request returns the same run. `submit_program` remains available for explicit staged
loading. Both paths retain source and configuration fingerprint checks.

Automatic loading is limited to simulation and records `simulation_fixture`, never
operator attestation or sensor evidence. Physical loading still requires the existing
operator console confirmation; MCP has no physical-confirmation capability. Neither
transport starts a second runtime or bypasses dispatch/resource gates.

Progress and terminal outcomes appear at the top of the run pane, before the layout.
Completion scrolls to the result once; subsequent polling preserves the user's scroll.
Registered material is displayed immediately below the outcome. Loading plans,
execution receipts and technical state remain available below it.

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

### Workstation labware editing

Click an occupied or empty rack position directly to open its dialog. It shows the
current contents and driver-compatible choices, including leaving a position empty.
Save once to validate and apply through the existing guarded endpoints; the dialog
waits for a confirmed receipt before closing. Unknown responses retain the request
identity for status inspection and are never automatically resent. Escape closes the
dialog and restores deck focus without cancelling an accepted save. No separate edit-mode button or off-screen editor is required.

`LabwareEditorPort` (`driver_framework/models.py`) is an optional offline device-factory
capability: `catalogue(path)` supplies compatible site/model choices and
`prepare(path, change)` returns a detached configuration and generic layout.
`ResidentLabwareInteractor` checks the current identity; `LabwareConfigurationInteractor`
saves a checked draft. Application uses the existing idle/resource/activation guards.
HTTP and DOM controls carry requests only. Hamilton implements native and generated
layouts; other drivers without the capability report editing unavailable. No vendor
files are read by the frontend. Editing neither loads labware nor confirms contents.
Existing native labware can be replaced or removed, including definitions outside
the execution catalogue. Installed definitions and site footprints determine editor
choices; this does not extend verified execution support. The form explains linked
setting cleanup before saving; the save feedback reports affected bindings, capacity,
well-map or tip-source settings. Clearing a stack includes all its objects. A missing tip source remains explicitly unconfigured
and rejects transfers before dispatch. Module/transport-dependent positions retain
their dedicated setup checks. E2E and desktop/mobile golden coverage: `tests/integration/test_console_labware.py`.
Deck tracks always share one horizontal scale, including mixed one-, two- and
multi-track carriers. The whole board can scroll; numeric labels on narrow carriers
and schematic vertical spacing do not change track widths.
New placements do not infer liquid capacity, reagent inventory, well mappings or program
bindings. Those remain explicit driver/experiment preparation inputs.


System Settings exposes **Racks and carriers** through the same offline layout
editor port. Driver-declared carrier targets have `kind: carrier`; Workstation
keeps labware targets. Check a replacement to save a detached proposal, then apply
through the existing idle/fingerprint gate. Compatible leaf labware keeps its
identity and site; canonical native transforms are regenerated. Colliding tracks,
unsupported stacks, coordinate associations and adjusted native frames are blocked
with reasons. Physical installation and experiment loading remain operator checks.


### Home and protocol files

`console`, `desktop` and `mcp` accept `--home` (default `~/Culsma`). The first
authorized file listing creates `projects/` and `results/` without replacing existing
files. Put `.culs` programs and their imported `.culs` libraries in `projects/`;
project subdirectories appear under Files. Non-program files stay on disk and are
not shown in this first browser. `results/` is available for user exports; resident
evidence continues to use its configured artifacts directory. `--program-root`
selects an existing source directory instead. The console shows the actual source
path and Refresh files rescans it.

Single-click inspects a captured program. Double-click or Run protocol automatically
checks preparation, submits the reviewed snapshot and starts simulation; errors stop
progress and are shown in the same Workstation. HTTP and MCP share the Program Manager
use cases. Overlapping reads cannot replace a newer selection; duplicate launch gestures
are collapsed and unknown submission responses retain their request identity. Drag/drop
and editing non-program files remain outside this initial slice.
