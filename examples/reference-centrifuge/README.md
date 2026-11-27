# Reference centrifuge workstation

This example executes five device effects through the ordinary Culsma CLI. It adds 50 µL to a sample well, moves the plate to a reference centrifuge, models a cycle at 300 × g for 5 minutes at 4 °C, returns the plate, and transfers 40 µL from the supernatant selection.

The Opentrons 8.8.2 simulator executes the pipette and deck movement commands. The Culsma reference centrifuge model supplies rotor state, configured load masses, modeled temperature and virtual time. The reference dock corresponds to slot B1 in the SDK. The run checks simulated control flow, including the identity of the plate and the producer of the selected liquid fraction. Physical positioning, actual sample temperature and biological separation are outside the model.

Use an environment with Culsma, Culsma OS and the matching Opentrons simulator plugin installed. Run these commands from this example directory with a fresh output directory for each run.

```sh
CULSMA_OS_STATION_ROOT="$PWD/runs/cooled/stations" CULSMA_OS_STATION_ID=reference \
  culsma run protocol.culs --driver os-opentrons-simulator --driver-config workstation.json \
  --artifacts-dir runs/cooled --json
python verify_run.py runs/cooled > runs/cooled/evidence.json
```

The same protocol with `workstation-uncooled.json` should exit unsuccessfully and report that the 4 °C request is unsupported. The verifier checks that there are no dispatched device effects.

```sh
CULSMA_OS_STATION_ROOT="$PWD/runs/uncooled/stations" CULSMA_OS_STATION_ID=reference \
  culsma run protocol.culs --driver os-opentrons-simulator --driver-config workstation-uncooled.json \
  --artifacts-dir runs/uncooled --json
python verify_run.py runs/uncooled --expect temperature-rejected > runs/uncooled/evidence.json
```

`run.json` holds the program result and diagnostics. `verify_run.py` reads the recorded device evidence in `culsma-os.sqlite3` and exports the five effects or the preflight rejection.
