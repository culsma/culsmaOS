import AppKit
import Foundation

// A Finder entry point only. The Python product owns startup and the native UI owns interaction.
let resources = Bundle.main.resourceURL!
let state = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/culsmaOS/preview")
do {
    try FileManager.default.createDirectory(at: state, withIntermediateDirectories: true,
        attributes: [.posixPermissions: 0o700])
    let logURL = state.appendingPathComponent("launcher.log")
    if !FileManager.default.fileExists(atPath: logURL.path) {
        FileManager.default.createFile(atPath: logURL.path, contents: nil,
            attributes: [.posixPermissions: 0o600])
    }
    let log = try FileHandle(forWritingTo: logURL)
    try log.seekToEnd()
    let process = Process()
    process.executableURL = resources.appendingPathComponent("runtime/bin/python3.11")
    process.arguments = ["-I", "-B", resources.appendingPathComponent("launch.py").path, "desktop"]
    process.standardInput = FileHandle.nullDevice
    process.standardOutput = log
    process.standardError = log
    process.currentDirectoryURL = state
    try process.run()
    process.waitUntilExit()
    if process.terminationStatus != 0 {
        throw NSError(domain: "culsmaOS", code: Int(process.terminationStatus),
            userInfo: [NSLocalizedDescriptionKey: "The preview could not start. See \(logURL.path)"])
    }
} catch {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    app.activate(ignoringOtherApps: true)
    let alert = NSAlert()
    alert.messageText = "culsmaOS could not start"
    alert.informativeText = error.localizedDescription
    alert.addButton(withTitle: "OK")
    alert.runModal()
    exit(1)
}
