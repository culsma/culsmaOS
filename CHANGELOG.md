# Changelog

## 0.2.0rc1 — Mac desktop test release

- Add the native desktop, experiment file browser/editor, loading review and user-facing results.
- Share file, experiment and configuration use cases with 43 authorized MCP tools.
- Synchronize external configuration changes while preserving unsaved human edits.
- Bundle a relocatable Python runtime, official Opentrons simulator and isolated MCP packages in a macOS arm64 DMG.
- Preserve experiment files, durable execution records and explicit unknown outcomes.
- Validate the installed product locally; physical instruments and Windows packaging remain outside this release.

## 0.1.1 — Public experimental preview

- Redact local filesystem paths from published evidence and repository history.
- Add an introductory README, functional architecture overview and copyable simulator examples.
- Separate build/test manifests from documentation and organize references, contracts and preparation records.
- Keep a compact public architecture overview; detailed design and diagram checks move to an independent internal workspace.
- Document resident readiness, simulator defaults and saved material results.
- Add software citation metadata and contributor, security and dependency notices.
- Publish compatible installation artifacts together with the OS release.
- Preserve the 0.1.0 runtime behavior; this release prepares distribution and documentation.

## 0.1.0 — First source preview

License: Apache-2.0.

- Run independent Culsma programs through one-shot CLI execution or a resident, persistent FIFO queue.
- Coordinate external device plugins, whole-run resource reservations, station placement and consumable usage.
- Preserve execution intent, device evidence, material registration and recovery checkpoints; retain isolation for unknown effects.
- Validate restricted transfer, thermal, shaking, magnetic and plate-motion profiles with the official Opentrons simulator; centrifuge protocol simulation is optional and third-party.
- Include complete PCR and reduced bead-buffer-exchange examples, architecture diagrams and local validation tools.

Experimental scope: one station, one worker and fixed configuration. GUI, scientific readout, shared physical reagent inventory and real-instrument acceptance are outside this preview. Compatible language/plugin snapshots are distributed separately; PyPI publication is deferred. The cancelled cloud test run is not passing acceptance evidence. No GitHub Actions workflows are included.
