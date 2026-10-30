# Third-party software

culsmaOS is licensed under Apache-2.0. Dependencies remain separate distributions
and retain their own licenses and notices.

| Component | Use | License |
| --- | --- | --- |
| Culsma | Independent language compiler and runtime | Apache-2.0 |
| Culsma Opentrons simulator plugin | External Culsma integration; not an official vendor product | Apache-2.0 |
| Opentrons Python API and shared data 8.8.2 | Official simulator used by the external plugin | Apache-2.0 |
| MCP Python SDK 2.3.0 | Isolated stdio bridge for external AI clients; included in the Mac product | MIT |
| Pydantic and pydantic-settings | External plugin configuration | MIT |

The release includes separately built compatibility wheels for the Culsma language
and the Culsma Opentrons simulator plugin. Their embedded license files apply to
those distributions. The Opentrons vendor packages are installed as dependencies;
they are not included as vendor source in the OS package.

Fixed plugin test inputs are recorded in
[the fixture provenance manifest](tests/fixtures/driver_framework/opentrons/provenance.json).
PyLabRobot (MIT) is an optional, separately installed integration and is not bundled.
Hamilton vendor software is not redistributed. These integrations do not imply
vendor endorsement or hardware certification.

When redistributing dependencies, retain their license and copyright notices and
any applicable upstream NOTICE files; identify changes to upstream files.
The OS license does not replace dependency licenses. The installed NumPy wheel
also includes notices for its bundled native libraries. See installed package
license files for that platform-specific inventory.

Upstream sources: [Opentrons](https://github.com/Opentrons/opentrons),
[PyLabRobot license](https://github.com/PyLabRobot/pylabrobot/blob/main/LICENSE),
[Apache-2.0 terms](https://www.apache.org/licenses/LICENSE-2.0).

### Flutter console fonts

The desktop console includes Roboto Regular and Medium under the Apache License 2.0.
The font license is provided in `frontend/console/assets/fonts/LICENSE.txt`.
Flutter itself and its SDK components retain their respective upstream licenses.


## Native file drop and highlighting

The native console uses `desktop_drop` 0.9.2 (Apache-2.0) and
`syntax_highlight` 0.4.0 (BSD-3-Clause). Flutter includes their package license
notices in the application license registry. The Culsma TextMate grammar is the
existing Culsma Syntax grammar, bundled as a first-party language asset.

The code editor bundles Roboto Mono from the Google Fonts project under the SIL
Open Font License 1.1. Its copyright and full license are included at
`frontend/console/assets/fonts/RobotoMono-OFL.txt`.

## Self-contained Mac preview

The desktop DMG additionally includes CPython 3.11.18 from Astral's
python-build-standalone distribution (Python-2.0/CNRI-Python and embedded-library
licenses). Its matching upstream `PYTHON.json` and complete `licenses/` directory
are retained under `Contents/Resources/PythonLicenses`.
The Mac product includes simulator dependencies as installed distributions, with
original wheel metadata and license/NOTICE files. `Product.json` lists each
isolated environment's exact package versions and license locations. NumPy's
bundled numerical-library notices remain in its installed wheel metadata.
Flutter's `NOTICES.Z` license registry and both font licenses are retained.
No Hamilton binaries, labware definitions or site-specific layouts are included.

Mac native binaries receive ad-hoc signatures during assembly; dependency source
code is unchanged. Input-wheel hashes describe the upstream inputs before signing.
