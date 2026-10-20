# culsmaOS native console

Flutter UI and Python resident form one local product and share the root version.
This first native slice covers graphical Layout editing and read-only System Information.
Other console pages remain in the existing browser console during migration.
The macOS embedder enables Flutter's native accessibility bridge for local agents
as well as the Dart semantics tree. This SDK-pinned integration must be rechecked
with external native AX inspection when updating FVM; Widget tests alone are not sufficient.

```sh
fvm install
fvm flutter pub get
fvm flutter analyze
fvm flutter test
```

`test/goldens/` contains reviewed reference images, not generated run reports.
To propose a visual change, run `fvm flutter test --update-goldens`, inspect the diff,
and rerun ordinary tests. Actual and diff images under `test/failures/` are ignored.
The SDK version, lockfile, bundled fonts and viewport dimensions define this baseline.

From the repository root, using the Python environment containing the matching
language and driver sources:

```sh
python tools/build_desktop.py
culsma-os desktop --driver-config examples/transfer/deck.json --program-root examples/transfer
python tools/test_desktop.py
```

The build command stages the native application locally. A signed standalone installer
is not produced by this development command. No independent frontend release is created.
Production credentials enter the native app over a private process pipe. The UI never
opens serial/USB devices or bypasses the owning backend Interactors.

The layout is schematic. Device geometry, catalogue and placement restrictions come
from the installed driver. Missing metadata is shown explicitly. Existing modules and
child labware are inspectable. The optional Hamilton configuration plugin adds
track/carrier/site proposal editing with full carrier footprint checks. Its metadata
is discovered through `culsma.configuration_profiles`, separately from execution drivers.
These proposals are not compiler environments or VENUS `.lay` files; backend activation
is refused for offline-only profiles. Module installation and `.lay` generation remain unavailable. Editing the proposed layout does not move real equipment.

The desktop uses persistent left navigation (bottom navigation on narrow windows),
a central schematic deck and a selected-position inspector. Open/create setups from
the folder control; unsaved changes prevent replacing the current proposal.
Device choices are supplied by installed profile metadata, not frontend catalogues.
To run both native E2E scenarios, install the optional Hamilton plugin and run
`python tools/test_desktop.py --with-hamilton`. The default command needs only Opentrons.
