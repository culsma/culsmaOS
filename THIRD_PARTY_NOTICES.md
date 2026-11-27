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

The 0.2.3 OS wheel and source archive use the independent [Culsma language](https://github.com/culsma/culsma) and [Opentrons driver](https://github.com/culsma/culsma-driver-opentrons) distributions. The [Hamilton driver](https://github.com/culsma/culsma-driver-hamilton) is available separately. Its upstream SDK notices accompany that driver. Their embedded license files apply to
those distributions. The Opentrons vendor packages are installed as dependencies;
they are not included as vendor source in the OS package.

Fixed plugin test inputs are recorded in
[the fixture provenance manifest](tests/fixtures/driver_framework/opentrons/provenance.json).
Hamilton vendor software is not redistributed. These integrations do not imply
vendor endorsement or hardware certification.

When redistributing dependencies, retain their license and copyright notices and
any applicable upstream NOTICE files; identify changes to upstream files.
The OS license does not replace dependency licenses. The installed NumPy wheel
also includes notices for its bundled native libraries. See installed package
license files for that platform-specific inventory.

Upstream sources: [Opentrons](https://github.com/Opentrons/opentrons),
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

## Flutter desktop runner templates

The desktop runner includes source generated from Flutter 3.47.7 templates. The upstream license follows.

Copyright 2014 The Flutter Authors. All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above
      copyright notice, this list of conditions and the following
      disclaimer in the documentation and/or other materials provided
      with the distribution.
    * Neither the name of Google Inc. nor the names of its
      contributors may be used to endorse or promote products derived
      from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
