# Third-party software

culsmaOS is licensed under Apache-2.0. Dependencies remain separate distributions
and retain their own licenses and notices.

| Component | Use | License |
| --- | --- | --- |
| Culsma | Independent language compiler and runtime | Apache-2.0 |
| Culsma Opentrons simulator plugin | External Culsma integration; not an official vendor product | Apache-2.0 |
| Opentrons Python API and shared data 8.8.2 | Official simulator used by the external plugin | Apache-2.0 |
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
