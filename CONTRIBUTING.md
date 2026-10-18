# Contributing

Start with the [architecture](docs/module/README.md) and [development guide](docs/development.md).
For a defect report, include the OS version, Python version, simulator/plugin
version, a minimal protocol and configuration, and the expected and actual outcome.
Remove credentials, personal data and private experimental inputs from reports.

Keep changes within the owning module. Preserve the independent language and
external-plugin boundaries, and keep execution intent, device evidence and material
registration distinct. Add behavioral tests for changed execution or recovery
rules and update the matching diagrams when the structure changes.

Run the relevant tests locally. Full release acceptance and builds also run locally;
do not add GitHub Actions workflows. Use English documentation and Conventional
Commits. Contributions are made under the repository's Apache-2.0 license.
