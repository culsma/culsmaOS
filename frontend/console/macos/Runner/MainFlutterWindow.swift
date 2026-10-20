import Cocoa
import FlutterMacOS

class MainFlutterWindow: NSWindow {
  let accessibilityAdapter = NativeAccessibilityAdapter()
  override func awakeFromNib() {
    let flutterViewController = FlutterViewController()
    let windowFrame = NSRect(x: self.frame.origin.x, y: self.frame.origin.y, width: 1100, height: 840)
    self.contentViewController = flutterViewController
    self.setFrame(windowFrame, display: true)
    self.minSize = NSSize(width: 390, height: 500)

    RegisterGeneratedPlugins(registry: flutterViewController)

    super.awakeFromNib()
    accessibilityAdapter.attach(to: self)
  }
}

/// Process-local embedder initialization for external accessibility clients.
/// Flutter 3.47.7 gates the native bridge separately from Dart ensureSemantics.
/// The notification is consumed by FlutterEngine, not the global system service.
/// Revalidate this integration with native AX inspection when upgrading the SDK.
class NativeAccessibilityAdapter {
  var observer: NSObjectProtocol?

  func attach(to window: NSWindow) {
    observer = NotificationCenter.default.addObserver(
      forName: NSWindow.didBecomeKeyNotification, object: window, queue: .main
    ) { [weak self] _ in self?.enable() }
    DispatchQueue.main.async { [weak self] in self?.enable() }
  }

  func enable() {
    NotificationCenter.default.post(
      name: NSNotification.Name("NSApplicationDidChangeAccessibilityEnhancedUserInterfaceNotification"),
      object: NSApp, userInfo: ["AXEnhancedUserInterface": true]
    )
  }

  deinit {
    if let observer = observer { NotificationCenter.default.removeObserver(observer) }
  }
}
