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

## Native station console (development checkout)

The console is a local Flutter application and is not included in the published
0.1.1 wheel. Build it locally with the pinned FVM SDK, then attach it to an
existing resident:

```sh
cd frontend/console
fvm flutter build macos --release --no-pub
cd ../..
culsma-os desktop --socket /tmp/culsma-console.sock --program-root examples
```

The native bundle must be staged at the path used by the desktop launcher when
running from source. Tests and local development use the same Python API owners;
there is no independently deployed frontend server. The older embedded pages
remain migration references; native startup does not serve those pages or their
credential bootstrap.

### Console navigation

| Window | Existing functionality |
| --- | --- |
| Files | User-workspace file browser, bounded preview, double-click review |
| Experiment | Loading plan/preferences, operator confirmation, status, pause/resume/cancel, result and evidence |
| Workstation | Current layout, container placement/replacement/removal, run history, supported simulated tip-box replacement |
| System Settings | Rack replacement and advanced saved layout/configuration editor |
| System Info | Verified active equipment declarations, device records, consumables, locks, reservations, driver metadata, runtime and service state |

One workbar opens or restores these windows. Experiments have separate windows.
Moving, minimizing or closing a window does not cancel an experiment. Unsaved
settings are retained. File drag-and-drop, hardware discovery, PAWS and physical
inventory detection are outside this migration.

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
the request ID in local application-support storage; an explicit retry uses that identity. No action is
automatically retried, and unknown outcomes retain isolation. This development
console supports one local operator; it is not a LAN service or user login system.

### Human and external AI operation

Native controls expose named accessibility elements and stable semantic IDs.
External AI uses MCP for program and loading operations, run controls and their
receipts, supported simulated tip replacement, and requesting native views.
The renderer reports whether a requested view was displayed; a display receipt
is not execution evidence. Both paths use the same authorized backend Interactors.
MCP cannot confirm physical loading on behalf of the operator.

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

### Shared console view control

`view_state` lists live renderer sessions, their `epoch`, `revision` and reported view.
Select an explicit session before `open_view(session_id, epoch, expected_revision,
request_id, view, entity_id)` or `reveal_entity(..., entity_id)`. Supported views are
`experiment`, `workstation`, `files`, `settings` and `system_info`. Experiment views
require a run ID; workstation entities are checked against the declared driver layout.
`view_request_status(request_id)` returns `accepted`, `displayed`, `deferred`,
`rejected` or `expired`. A display receipt is a renderer report, not execution evidence.

The console HTTP process and stdio MCP process share a presentation-only SQLite
store derived from the same resident socket path (`<socket>.views.sqlite3`). The store
is created lazily when a renderer registers. `ConsoleSettings.view_store_path` permits
a trusted composition override; no HTTP or MCP argument accepts a database path.
Credentials remain process-local and in memory. Only an Auth-issued renderer
credential can register, report or acknowledge its own session. MCP receives read
and presentation capabilities, without renderer or physical-confirmation authority.

`ConsoleShell` connects the current console views to this contract using bounded
polling. It opens the existing views and highlights declared items, preserving unsaved
edits and open editors by reporting `deferred`. It does not execute program or
configuration commands. Sessions expire after 15 seconds without a heartbeat;
unhandled requests expire after 30 seconds and are never replayed on a new renderer.
Request IDs are idempotent; changed payloads or stale view revisions are rejected.
Closing the renderer leaves resident runs and instrument reservations unchanged.
This implements the shared interaction channel; the proposed windowed desktop
appearance and PAWS/resource inventory integration remain later work.

The three-layer module is `console_interaction/{interactors,repository,models}.py`.
`ConsoleApplicationLifecycleInteractor` is the renamed console launcher; view control
uses `ViewStateReadInteractor`, `ViewRequestInteractor` and `RendererSessionInteractor`.
The protocol/browser acceptance is `tests/integration/test_console_view_interaction.py`;
its isolated MCP subprocess and browser Golden check do not dispatch device actions.

Single-clicking a protocol previews its source. In the native console, double-clicking
checks the protocol and opens its loading review. Choosing **Run simulation** then sends
one durable `start` request. The resident records automatic startup in the queue and owns final planning,
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
The native outcome page renders `lab_report_v1` products, starting materials, reagent
consumption, container/instrument requirements and process counts. OS execution evidence
remains separate. Legacy material-only results prefer display labels and conceal internal
allocation identifiers; incomplete runs label their reports as partial results.
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
HTTP and native controls carry requests only. Hamilton implements native and generated
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

Files opens the user workspace, `~/Culsma` by default (`--home` changes it).
This is separate from application binaries, source code and internal runtime state.
The workspace shows user content: Experiments and Results. Existing experiments
remain in `projects/`, displayed as Experiments; no existing files are moved.
`--program-root` retains an explicitly configured experiment directory, also available
as an Experiments shortcut. `--file-root` can explicitly select a deployment's user
workspace directory; it must not point at the application package or source checkout.

The native browser provides folder navigation, back/forward/up, breadcrumbs,
folder trees, file metadata and bounded UTF-8 previews. Directory reads are paged;
hidden files, links, special files and execution snapshot storage cannot be opened.
Browsing is read-only. HTTP `/api/v1/files` and MCP `file_roots`, `list_directory`,
`preview_file` delegate to the same authorized File System Interactor.

Single-click previews a file; double-click opens a folder or checks a `.culs` program.
The native review lists the proposed container models, track/site locations,
initial liquid amounts, empty wells and configured tip positions. **Run simulation**
is an explicit action using the current simulated inventory, not a side-effect-free
static check. Simulation results are labelled. **Run on hardware** remains disabled:
the current OS runtime accepts simulation devices only. The preview exposes this
capability as `execution_options`; it does not claim a hardware connection.
Confirmation uses the checked source snapshot and configuration fingerprint. Stock
and device checks still run before dispatch; preview does not reserve inventory.
Execution still belongs to Program Manager. Programs opened through the workspace root use
`source_scope="installation"`; the default `"programs"` retains existing API
behavior. Workspace-root snapshots include only the selected program and its transitive
Culsma imports. They do not scan application files. Launches retain the exact
source scope, snapshot and request identity when a response is unknown.


### Native console window framework

The product UI is the Flutter application in `frontend/console`. `culsma-os desktop`
starts its local API with static pages and browser credential bootstrap disabled.
Console and renderer credentials travel through the private child stdin pipe.
The older embedded-page preview remains only as migration/reference material.

`NativeConsoleInteractor` owns renderer-local window state; `ConsoleDesktop` and
`ConsoleNativeWindow` render the workbar and windows. Four fixed application entries
open or restore their own windows; only experiments add separate task entries.
Closing a view never cancels a run. Unsaved settings cannot be closed or minimized.
Files uses the existing Program Manager start operation and retains an unresolved
request identity in application-support storage; it is not automatically resent.
`NativeRendererInteractor` uses the existing renderer session protocol for MCP open
and reveal requests. Display receipts remain presentation reports.

Native views cover file browsing/preview/start, run results/history, direct imported-deck
position editing, loading plans and confirmation, the existing layout editor and
system facts and detailed resource accounting. Pause/resume/cancel actions retain exact request identities and read worker receipts; acknowledgement is not application. System Info reads saved active origins separately from editable proposals. System Settings also presents compatible rack replacements separately
from Workstation container edits. Position choices come from the driver catalogue. One save prepares
and applies a checked draft; the editor waits for its receipt and the visible
active fingerprint. Loading windows show the deck, initial contents, supplies and
placement preferences. A changed shared plan invalidates operator acknowledgement.
Running and terminal windows keep the loading plan collapsed; outcome and material
results stay first. A loading confirmation records preparation, not execution success.
Pending mutation identities persist in application-support storage; status polling
never repeats a write. Backend behavior and human-confirmation permissions are unchanged.

Local checks: Flutter unit/widget tests and Golden comparisons; `tools/test_native_shell.py`
starts a real macOS Flutter app against isolated OS/HTTP/MCP owners and a labelled
device double. It verifies a nested protocol tree, pause/resume/cancel with applied
receipts, results, window restoration and an MCP display receipt. No remote simulator or physical instrument is used by this test.

`tools/test_native_operations.py` checks native diagram remove/place and explicit
loading confirmation through the real OS/HTTP boundary with an isolated device
double. It does not use or replenish the live preview inventory.


Native accessibility remains enabled for screen readers and external AI clients.
The pinned Flutter 3.47.7 tooltip overlay path can corrupt native AX trees during
hover and view transitions (flutter/flutter#182444, #175041). The console-wide
`NativeAccessibilityScope` suppresses hover tooltips while retaining explicit
control labels and actions. Native file E2E includes pointer hover and rejects AX
tree errors in the process log; revisit this guard after an SDK fix is verified.


Run views use Program Manager's `RunGuidanceInteractor` through the existing HTTP
and MCP observation paths. Verified preparation failures offer concrete next steps;
unknown outcomes do not offer a simple restart. Tip replacement requires the existing
acknowledged supply workflow and never restarts a protocol automatically. Historical
run status and diagnostics are unchanged. Raw errors, run identifiers, semantic step
counts and execution evidence remain available under Technical details.

The native accessibility scope also retains an explicit semantic container above
Navigator. Modal barriers may remove the exposed desktop subtree; the container
prevents its children from merging into the engine root during dialog transitions.
Keep native semantics enabled. `tools/test_native_accessibility.py` exercises 12
supply-dialog cancellations and an acknowledged replacement against in-memory
supplies, rejects AX-tree errors in native logs, and asserts that no run starts.
This is a regression check, not a guarantee against every upstream engine defect.

The native embedder owns the semantics lifecycle. Do not retain an independent
Dart `ensureSemantics()` handle: after native accessibility detach/attach, the
engine creates an empty bridge while that handle retains an incremental Dart tree.
The real native inventory E2E now reconnects the bridge between runs and during
tip replacement. Its test binding also uses platform-owned semantics. A debug-only,
explicitly opted-in native notification probe is absent from release builds.
The original App reproduced the crash under this regression; the corrected App
passed the same sequence. This does not disable accessibility or clear run state.
