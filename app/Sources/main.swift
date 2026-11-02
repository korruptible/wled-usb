import AppKit

final class Controller: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var statusItem: NSStatusItem!
    private var bridge: BridgeProcess!
    private var window: WebWindow?
    private var tap: AudioTap?
    private var analyzer: Analyzer?
    private var triggers: Triggers!
    private var level: Float = 0
    private var audioState = "son : inactif"

    private let bridgeLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let audioLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let levelLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let audioToggle = NSMenuItem(title: "Activer le son du Mac",
                                         action: #selector(toggleAudio), keyEquivalent: "")

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = MenuIcon.image()
        statusItem.button?.appearsDisabled = true
        statusItem.button?.toolTip = "WLED USB" 

        let menu = NSMenu()
        menu.addItem(bridgeLine)
        menu.addItem(audioLine)
        menu.addItem(levelLine)
        menu.addItem(.separator())
        menu.addItem(audioToggle)
        menu.addItem(triggerRoot)
        menu.addItem(NSMenuItem(title: "Ouvrir l'interface",
                                action: #selector(openInterface), keyEquivalent: "o"))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quitter", action: #selector(quit), keyEquivalent: "q"))
        menu.items.forEach { $0.target = self }
        statusItem.menu = menu

        bridge = BridgeProcess { [weak self] in self?.refresh() }
        bridge.start()
        triggers = Triggers(endpoint: bridge.url.appendingPathComponent("bridge/notify"))
        buildTriggerMenu()

        Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            self?.refresh()
        }
    }

    @objc private func toggleAudio() {
        if let running = tap {
            running.stop()
            tap = nil
            analyzer = nil
            level = 0
            audioState = "son : inactif"
            audioToggle.title = "Activer le son du Mac"
            return
        }
        analyzer = Analyzer { [weak self] rms, bands in
            self?.bridge.send(rms: rms, bands: bands)
        }
        let starting = AudioTap { [weak self] samples, channels, rate in
            guard !samples.isEmpty else { return }
            var sum: Float = 0
            for sample in samples { sum += sample * sample }
            self?.level = (sum / Float(samples.count)).squareRoot()
            self?.analyzer?.feed(samples, channels: channels, rate: rate)
        }
        do {
            try starting.start()
            tap = starting
            audioState = "son : capture active"
            audioToggle.title = "Couper le son du Mac"
        } catch {
            audioState = "son : " + error.localizedDescription
        }
    }

    private let triggerRoot = NSMenuItem(title: "Déclencheurs", action: nil, keyEquivalent: "")
    private let watchedRoot = NSMenuItem(title: "Applications surveillées",
                                         action: nil, keyEquivalent: "")

    private func buildTriggerMenu() {
        let submenu = NSMenu()
        for trigger in Trigger.all {
            let item = NSMenuItem(title: trigger.label,
                                  action: #selector(toggleTrigger(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = trigger.key
            item.state = triggers.enabled(trigger.key) ? .on : .off
            if trigger.needsCalendar { item.toolTip = "Demande l'accès au calendrier" }
            submenu.addItem(item)
            if trigger.key == "app" {
                let apps = NSMenu()
                apps.delegate = self
                watchedRoot.submenu = apps
                submenu.addItem(watchedRoot)
            }
        }
        triggerRoot.submenu = submenu
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        guard menu === watchedRoot.submenu else { return }
        menu.removeAllItems()

        var names = Set(triggers.watchedApps)
        for app in NSWorkspace.shared.runningApplications
        where app.activationPolicy == .regular {
            if let name = app.localizedName { names.insert(name) }
        }

        for name in names.sorted(by: { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }) {
            let item = NSMenuItem(title: name, action: #selector(toggleWatched(_:)),
                                  keyEquivalent: "")
            item.target = self
            item.representedObject = name
            item.state = triggers.watches(name) ? .on : .off
            menu.addItem(item)
        }
    }

    @objc private func toggleWatched(_ sender: NSMenuItem) {
        guard let name = sender.representedObject as? String else { return }
        triggers.toggleWatched(name)
        sender.state = triggers.watches(name) ? .on : .off
    }

    @objc private func toggleTrigger(_ sender: NSMenuItem) {
        guard let key = sender.representedObject as? String,
              let trigger = Trigger.all.first(where: { $0.key == key }) else { return }
        triggers.toggle(trigger) { [weak self] in
            sender.state = self?.triggers.enabled(key) == true ? .on : .off
        }
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls where url.scheme == "wledusb" {
            let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
            let value = { (name: String) in items.first { $0.name == name }?.value }
            var request = URLRequest(url: bridge.url.appendingPathComponent("bridge/notify"))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: [
                "source": "url",
                "app": value("app") ?? "Raccourci",
                "title": value("title") ?? "",
                "pattern": value("pattern") ?? "info",
                "priority": Int(value("priority") ?? "5") ?? 5,
            ])
            URLSession.shared.dataTask(with: request).resume()
        }
    }

    @objc private func openInterface() {
        if window == nil {
            window = WebWindow(url: bridge.url)
        }
        window?.show()
    }

    private func refresh() {
        switch bridge.state {
        case .running:  bridgeLine.title = "pont : en marche sur \(bridge.url.port ?? 0)"
        case .stopped:  bridgeLine.title = "pont : arrêté"
        case .failed(let why): bridgeLine.title = "pont : " + why
        }
        audioLine.title = audioState
        statusItem.button?.appearsDisabled = tap == nil
        let db = level > 0 ? 20 * log10(level) : -120
        let bars = max(0, min(20, Int((db + 60) / 3)))
        levelLine.title = "niveau  " + String(repeating: "▇", count: bars)
            + String(repeating: "·", count: 20 - bars)
    }

    @objc private func quit() {
        tap?.stop()
        bridge.stop()
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let controller = Controller()
app.delegate = controller
app.setActivationPolicy(.accessory)
app.run()
