# culsmaOS 0.2.0rc1 Mac preview

Apple Silicon Mac, macOS 15 or later. This experimental package runs the official
Opentrons simulator locally. It does not connect to physical instruments.
Python, the simulator and an isolated MCP bridge are included; no developer tools
or separate Python installation are needed. Windows packaging is not yet accepted.

## Install and try

1. Download the `.dmg` from the [0.2.0rc1 prerelease](https://github.com/culsma/culsmaOS/releases/tag/0.2.0rc1).
2. Open it and drag **CulsmaOS Preview.app** into **Applications**. Eject the disk image.
3. Open **CulsmaOS Preview**. The preview is ad-hoc signed, not Apple notarized.
   If macOS blocks it, review **System Settings → Privacy & Security → Open Anyway**.
4. Open **Files → Experiments → Transfer → transfer.culs**. Double-click the file,
   review the preparation, and choose the simulation action shown by the console.
5. A completed transfer leaves 100 µL in each tube. Results are calculated from
   simulated execution; no physical device is operated.

The preview creates `~/Culsma Preview/projects` and `~/Culsma Preview/results`.
Configuration and logs are under `~/Library/Application Support/culsmaOS/preview`.
Existing experiments and station configuration are preserved on subsequent starts.
Closing the UI leaves its local resident running so that MCP can still inspect it.

## Connect an external AI

Open the App first. For a stdio MCP client, use this command with no arguments:

```text
/Applications/CulsmaOS Preview.app/Contents/MacOS/culsma-mcp
```

For Codex, add this entry to the user MCP configuration, or use the equivalent
MCP settings screen:

```toml
[mcp_servers.culsma_os]
command = "/Applications/CulsmaOS Preview.app/Contents/MacOS/culsma-mcp"
```

For JSON-based clients, the App writes a configuration snippet to
`~/Library/Application Support/culsmaOS/preview/mcp-config.json` on launch.
If you install elsewhere, use that generated command rather than the example path.
Restart or reconnect the AI client's MCP session after adding the server.
No token needs to be copied. The bridge and UI share the same station, files,
configuration database and request receipts. Physical loading confirmation is
reserved for a person; AI cannot assert that it inspected a real deck.

Try asking the AI to list experiment files, inspect `Transfer/transfer.culs`,
show the workstation, or read the current configuration. Changes to station setup
require the current revision/fingerprint and an explicit apply operation.

Codex configuration follows the [official MCP documentation](https://learn.chatgpt.com/docs/extend/mcp).
The App does not change your AI client's configuration automatically.

## Troubleshooting and removal

Startup logs: `~/Library/Application Support/culsmaOS/preview/launcher.log` and
`resident.log`. The following commands use the bundled runtime:

```sh
"/Applications/CulsmaOS Preview.app/Contents/MacOS/culsma-status"
"/Applications/CulsmaOS Preview.app/Contents/MacOS/culsma-stop"
```

Close the UI and stop the resident before replacing or removing the App.
Removing the App preserves experiments and run records. This preview does not
install a system service, alter system Python, or install instrument software.

Dependency versions and license locations are recorded in
`CulsmaOS Preview.app/Contents/Resources/Product.json`. Python license texts,
wheel license files and Flutter's license registry are included in the bundle.
