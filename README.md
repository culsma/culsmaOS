# culsmaOS

**Scope: one station, one worker, fixed configuration, simulator validation. Runtime modules have minimal implementations; device and language coverage remains partial.**

Source preview: the compatible core and simulator snapshots are not published on a package index. Public Culsma `1.0.8` is incompatible. The [dependency contract](design/distribution-contract.json) pins private wheels to exact commits; it does not publish or modify either dependency repository. [Preparation status](design/public-preview-contract.json).

[Architecture](diagrams/abstract-machine-os-functional-units-v1.svg) · [Runtime overview](diagrams/modules/phase_one_framework_flowcharts-2.svg) · [Execution sequence](diagrams/modules/phase_one_framework_sequences-1.svg) · [Module diagrams](docs/module/README.md) · [Acceptance evidence](docs/evidence/station-workspace-20261017.json)

| Language / capability family | Integrated with restricted profiles | Not integrated |
| --- | --- | --- |
| Transfer | Liquid transfer, well selection and groups, restricted eight-channel columns and plates | General mass conversion, liquid methods and arbitrary containers |
| Environment | Temperature holds/incubation; temperature, thermocycler with explicit lid, and heater-shaker modules | thermal_program, CO2/humidity, general nested environments, simultaneous heating and shaking |
| Agitation | Orbital shaking; plate-centrifuge protocol simulation | vortex, invert, flick, stir, rotation; linear/rock shaking modes |
| Separation | Restricted magnetic separation (active module / Flex magnetic block) and in-place centrifugal separation | Filtration, disruption, temperature-controlled centrifugation and physical MicroSpin/HiG supernatant removal |
| Fractionation | — | Density gradients, chromatography and fraction collection |
| Readout | MeasurementSystem is reserved | img / ecp / phy acquisition, results and instrument interfaces |

[Complete PCR thermal-cycle example](examples/pcr-benchmark/flow.svg) retains 30 cycles / 92 holds and the original `high_precision` / `low_carryover` constraints, mapped to explicit liquid methods and fresh tips. Missing method configuration is rejected.

[Magnetic bead buffer exchange](examples/magnetic-buffer-exchange/flow.svg) validates initial capture and two static washes, including magnetic release, refill and recapture. This is a reduced independent workflow, not the full Module05. [Flex profile](examples/magnetic-buffer-exchange/deck-flex.json) reuses the same program with three gripper docking and three removal operations.

[Machine-readable coverage and sources](design/instrument-capability-map.json). Flex plate motion, temperature, shaking, magnetic blocks and [multi-module execution](examples/flex-workstation/flow.svg) are validated; [magnetic-block example](examples/magnetic-block-docking/protocol.culs) includes plate-removal release. Stacker and other docks are not integrated. Hamilton has an independent driver; its physical OS chain is not accepted. Centrifugation uses third-party protocol simulation, not physical BioNex HiG acceptance.

| Runtime area | Current implementation |
| --- | --- |
| Programs | Compilation, hosted runtime, persistent FIFO, two scheduling levels and whole-run reservations |
| Execution | Side-effect-free preparation → durable intent → device call → evidence → material registration → checkpoint |
| Faults / finalization | Confirmed actions are not replayed; unknown effects retain isolation; terminal state follows confirmed finalization and resource release |
| State ownership | Programs/material/evidence belong to the run store; devices/positions/pending motion/consumables/parent reservations belong to the station store |
| Entry points | One-shot run or resident serve; submit, status, pause/resume/cancel and device-status |

```sh
# Set CULSMA_CORE_SOURCE and CULSMA_SIMULATOR_SOURCE to the matching source checkouts.
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements/build.txt
python tools/build_preview_dependencies.py --core "$CULSMA_CORE_SOURCE" --simulator "$CULSMA_SIMULATOR_SOURCE" --output run-artifacts/dependency-wheels
python -m build --no-isolation
python -m pip install --find-links run-artifacts/dependency-wheels --constraint requirements/preview-constraints.txt 'dist/culsma_os-0.1.0-py3-none-any.whl[simulator,dev]'
culsma-os run examples/heater-shaker-docking/protocol.culs --station-id bench-a --host-db run-artifacts/once.sqlite3 --driver-config examples/heater-shaker-docking/deck.json --artifacts-dir run-artifacts/once
culsma-os serve --station-id bench-a --socket /tmp/culsma-os.sock --host-db run-artifacts/host.sqlite3 --driver-config examples/heater-shaker-docking/deck.json --artifacts-dir run-artifacts/host
culsma-os submit examples/heater-shaker-docking/protocol.culs --socket /tmp/culsma-os.sock
culsma-os device-status --socket /tmp/culsma-os.sock
culsma-os host-stop --socket /tmp/culsma-os.sock
```

`culsma run` remains independently owned by the language. A compatible generic program-executor plugin can hand the complete program to the same one-shot OS path through `--driver`. `run` does not connect to `serve` automatically. `--station-id` / `CULSMA_OS_STATION_ID` and `CULSMA_OS_STATION_ROOT` identify a station. Changing the run database or artifact directory does not reset shared device state. Legacy records migrate only when evidence agrees; conflicts reject and original files remain. Editing configuration does not authorize moving hardware or resetting plate positions.

`device-status` reports recorded state, not sensor measurements. Unconfirmed positions and quantities are null. Runs retain independent simulated inputs; there is no authoritative shared physical reagent inventory. GUI, general manual reconciliation, asynchronous device-task supervision, parallel execution and measured-model correction are not implemented.

Protocol acceptance covers PCR, OT-2 bead washing and Flex bead washing: normal completion, rejection and unknown outcomes (9 cells / 35 tests).

```sh
python -m tests.acceptance.protocols --output-dir run-artifacts/protocol-acceptance/first-run
```

Use a new output directory. `summary.json`, JUnit, logs, input snapshots, run stores and station stores are retained. Missing, skipped or failed cases fail the gate. [Manifest](design/protocol-acceptance-suite.json) · [Evidence](docs/evidence/protocol-acceptance-20261018.json).

Resident full-protocol acceptance covers OT-2/Flex continuity, tip-rack exhaustion, unknown-outcome blocking, cancellation finalization and successor execution (5 tests). Each station reuses one device session; material inputs remain independent per run.

```sh
python -m pytest tests/integration/test_resident_protocols.py -q
```

[Contract](design/resident-protocol-acceptance.json) · [Evidence](docs/evidence/resident-protocols-20261018.json).

Different complete programs share one [fixed station](examples/resident-station/deck.json) with [explicit program bindings/routes](examples/resident-station/workspaces.json). Submit the unchanged PCR and bead programs in sequence. Station resources continue between jobs; experimental inputs are simulated independently.

```sh
# Terminal 1
culsma-os serve --station-id pcr-beads --socket /tmp/culsma-mixed.sock --host-db run-artifacts/resident-station/os.sqlite3 --driver-config examples/resident-station/deck.json --workspace-config examples/resident-station/workspaces.json --artifacts-dir run-artifacts/resident-station
# Terminal 2
culsma-os submit examples/pcr-benchmark/protocol.culs --socket /tmp/culsma-mixed.sock
culsma-os submit examples/magnetic-buffer-exchange/protocol.culs --socket /tmp/culsma-mixed.sock
```

Unified resident acceptance covers program profiles, mixed protocols, Flex position continuity, cancellation, unknown outcomes, restart and architecture (40 tests).

```sh
python -m tests.acceptance.resident --output-dir run-artifacts/resident-acceptance/first-run
```

[Evidence](docs/evidence/mixed-resident-protocols-20261018.json) · [Workspace contract](design/program-workspace-contract.json) · [Submission sequence](diagrams/modules/program_manager_sequences-1.svg) · [Flowchart](diagrams/modules/program_manager_flowcharts-3.svg) · [Manifest](design/resident-acceptance-suite.json). Checkpoints retain compiled plans and configuration snapshots; recovery does not reload program source. Restart still requires matching station and service configuration.

[Runtime contract](design/framework-baseline.json) · [Review map](docs/review/framework-functional-review.md).
