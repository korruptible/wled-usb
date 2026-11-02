import AppKit
import WebKit

final class WebWindow: NSWindowController {
    private let webView = WKWebView()

    convenience init(url: URL) {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 760),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "WLED USB"
        window.center()
        self.init(window: window)
        window.contentView = webView
        webView.load(URLRequest(url: url))
    }

    func reload() {
        webView.reload()
    }

    func show() {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
    }
}
