import AppKit
import EventKit

struct Trigger {
    let key: String
    let pattern: String
    let needsCalendar: Bool

    var label: String { L10n.t("trigger." + key) }

    static let all = [
        Trigger(key: "wake", pattern: "info", needsCalendar: false),
        Trigger(key: "unlock", pattern: "info", needsCalendar: false),
        Trigger(key: "lock", pattern: "info", needsCalendar: false),
        Trigger(key: "app", pattern: "slack", needsCalendar: false),
        Trigger(key: "mesh", pattern: "urgent", needsCalendar: false),
        Trigger(key: "meeting", pattern: "call", needsCalendar: true),
    ]
}

final class Triggers {
    private let endpoint: URL
    private let store = EKEventStore()
    private var meshWasUp = true
    private var announced = Set<String>()
    private var timer: Timer?

    private(set) var lastFired = ""

    var watchedApps: [String] {
        get {
            UserDefaults.standard.stringArray(forKey: "trigger.app.names") ?? ["Slack"]
        }
        set {
            UserDefaults.standard.set(newValue.sorted(), forKey: "trigger.app.names")
        }
    }

    func watches(_ name: String) -> Bool {
        watchedApps.contains(name)
    }

    func toggleWatched(_ name: String) {
        var names = watchedApps
        if let index = names.firstIndex(of: name) {
            names.remove(at: index)
        } else {
            names.append(name)
        }
        watchedApps = names
    }

    init(endpoint: URL) {
        self.endpoint = endpoint
        register()
        timer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in
            self?.sweep()
        }
    }

    func enabled(_ key: String) -> Bool {
        UserDefaults.standard.bool(forKey: "trigger.\(key)")
    }

    func toggle(_ trigger: Trigger, completion: @escaping () -> Void) {
        let next = !enabled(trigger.key)
        guard next, trigger.needsCalendar else {
            UserDefaults.standard.set(next, forKey: "trigger.\(trigger.key)")
            completion()
            return
        }
        store.requestFullAccessToEvents { granted, _ in
            DispatchQueue.main.async {
                UserDefaults.standard.set(granted, forKey: "trigger.\(trigger.key)")
                if !granted { self.lastFired = L10n.t("calendar.denied") }
                completion()
            }
        }
    }

    private func register() {
        let workspace = NSWorkspace.shared.notificationCenter
        workspace.addObserver(forName: NSWorkspace.didWakeNotification,
                              object: nil, queue: .main) { [weak self] _ in
            self?.fire("wake", title: L10n.t("fired.wake"))
        }
        for (name, key, title) in [
            (NSWorkspace.didLaunchApplicationNotification, "app", "fired.launched"),
            (NSWorkspace.didTerminateApplicationNotification, "app", "fired.terminated"),
        ] {
            workspace.addObserver(forName: name, object: nil, queue: .main) { [weak self] note in
                guard let self,
                      let app = note.userInfo?[NSWorkspace.applicationUserInfoKey]
                          as? NSRunningApplication,
                      let name = app.localizedName,
                      self.watches(name) else { return }
                self.fire(key, title: "\(name) \(L10n.t(title))")
            }
        }

        let distributed = DistributedNotificationCenter.default()
        distributed.addObserver(forName: .init("com.apple.screenIsLocked"),
                                object: nil, queue: .main) { [weak self] _ in
            self?.fire("lock", title: L10n.t("fired.lock"))
        }
        distributed.addObserver(forName: .init("com.apple.screenIsUnlocked"),
                                object: nil, queue: .main) { [weak self] _ in
            self?.fire("unlock", title: L10n.t("fired.unlock"))
        }
    }

    private func sweep() {
        if enabled("mesh") {
            let up = Self.meshIsUp()
            if meshWasUp && !up {
                fire("mesh", title: L10n.t("fired.mesh"))
            }
            meshWasUp = up
        }
        if enabled("meeting") {
            upcomingMeeting()
        }
    }

    private func upcomingMeeting() {
        guard EKEventStore.authorizationStatus(for: .event) == .fullAccess else { return }
        let now = Date()
        let predicate = store.predicateForEvents(withStart: now,
                                                 end: now.addingTimeInterval(360),
                                                 calendars: nil)
        for event in store.events(matching: predicate) {
            let identifier = event.eventIdentifier ?? event.title ?? ""
            let delay = event.startDate.timeIntervalSince(now)
            guard delay > 0, delay <= 300, !announced.contains(identifier) else { continue }
            announced.insert(identifier)
            fire("meeting", title: event.title ?? L10n.t("fired.meeting"))
        }
        if announced.count > 200 { announced.removeAll() }
    }

    private static func meshIsUp() -> Bool {
        var pointer: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&pointer) == 0, let first = pointer else { return false }
        defer { freeifaddrs(pointer) }
        var cursor: UnsafeMutablePointer<ifaddrs>? = first
        while let entry = cursor {
            if let address = entry.pointee.ifa_addr,
               address.pointee.sa_family == UInt8(AF_INET) {
                var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                if getnameinfo(address, socklen_t(address.pointee.sa_len), &host,
                               socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 {
                    let text = String(cString: host)
                    let parts = text.split(separator: ".").compactMap { Int($0) }
                    if parts.count == 4, parts[0] == 100, (64...127).contains(parts[1]) {
                        return true
                    }
                }
            }
            cursor = entry.pointee.ifa_next
        }
        return false
    }

    private func fire(_ key: String, title: String) {
        guard enabled(key),
              let trigger = Trigger.all.first(where: { $0.key == key }) else { return }
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: [
            "source": "macos",
            "app": trigger.label,
            "title": title,
            "pattern": trigger.pattern,
            "priority": 5,
        ])
        URLSession.shared.dataTask(with: request).resume()
        lastFired = title
    }
}
