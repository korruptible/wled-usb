import Foundation

enum L10n {
    static let supported = ["en", "fr"]

    private(set) static var language = systemLanguage()

    static func systemLanguage() -> String {
        for tag in Locale.preferredLanguages {
            let primary = String(tag.prefix(while: { $0 != "-" && $0 != "_" })).lowercased()
            if supported.contains(primary) { return primary }
        }
        return "en"
    }

    @discardableResult
    static func apply(_ code: String) -> Bool {
        guard supported.contains(code), code != language else { return false }
        language = code
        return true
    }

    static func t(_ key: String) -> String {
        table[language]?[key] ?? table["en"]?[key] ?? key
    }

    static func t(_ key: String, _ argument: String) -> String {
        t(key).replacingOccurrences(of: "%@", with: argument)
    }

    private static let table: [String: [String: String]] = [
        "en": [
            "audio.off": "audio: off",
            "audio.on": "audio: capturing",
            "audio.prefix": "audio: ",
            "audio.enable": "Turn on computer audio",
            "audio.disable": "Turn off computer audio",
            "bridge.running": "bridge: running on %@",
            "bridge.stopped": "bridge: stopped",
            "bridge.prefix": "bridge: ",
            "bridge.exited": "the bridge stopped (code %@)",
            "level": "level",
            "menu.triggers": "Triggers",
            "menu.watched": "Watched applications",
            "menu.open": "Open the interface",
            "menu.quit": "Quit",
            "menu.calendarTip": "Requires calendar access",
            "trigger.wake": "Mac wakes up",
            "trigger.unlock": "Screen unlocked",
            "trigger.lock": "Screen locked",
            "trigger.app": "A watched app starts or quits",
            "trigger.mesh": "Tailscale or NetBird goes down",
            "trigger.meeting": "Meeting in 5 minutes",
            "fired.wake": "Mac woke up",
            "fired.lock": "Screen locked",
            "fired.unlock": "Screen unlocked",
            "fired.mesh": "Mesh network unavailable",
            "fired.meeting": "Meeting",
            "fired.launched": "started",
            "fired.terminated": "quit",
            "calendar.denied": "calendar denied",
            "shortcut": "Shortcut",
            "tap.unsupported": "system audio capture needs macOS 14.2 or newer",
            "tap.failed": "tap creation refused (%@): is the “system audio recording” permission missing?",
            "tap.aggregate": "could not create the aggregate device (%@)",
            "tap.io": "could not start the audio stream (%@)",
        ],
        "fr": [
            "audio.off": "son : inactif",
            "audio.on": "son : capture active",
            "audio.prefix": "son : ",
            "audio.enable": "Activer le son de l'ordinateur",
            "audio.disable": "Couper le son de l'ordinateur",
            "bridge.running": "pont : en marche sur %@",
            "bridge.stopped": "pont : arrêté",
            "bridge.prefix": "pont : ",
            "bridge.exited": "le pont s'est arrêté (code %@)",
            "level": "niveau",
            "menu.triggers": "Déclencheurs",
            "menu.watched": "Applications surveillées",
            "menu.open": "Ouvrir l'interface",
            "menu.quit": "Quitter",
            "menu.calendarTip": "Demande l'accès au calendrier",
            "trigger.wake": "Réveil de l'ordinateur",
            "trigger.unlock": "Déverrouillage de l'écran",
            "trigger.lock": "Verrouillage de l'écran",
            "trigger.app": "Une app surveillée démarre ou se ferme",
            "trigger.mesh": "Tailscale ou NetBird tombe",
            "trigger.meeting": "Réunion dans 5 minutes",
            "fired.wake": "Ordinateur réveillé",
            "fired.lock": "Écran verrouillé",
            "fired.unlock": "Écran déverrouillé",
            "fired.mesh": "Réseau maillé indisponible",
            "fired.meeting": "Réunion",
            "fired.launched": "démarre",
            "fired.terminated": "se ferme",
            "calendar.denied": "agenda refusé",
            "shortcut": "Raccourci",
            "tap.unsupported": "la capture audio système demande macOS 14.2 ou plus récent",
            "tap.failed": "création du tap refusée (%@) : autorisation « enregistrement audio du système » manquante ?",
            "tap.aggregate": "création du périphérique agrégé impossible (%@)",
            "tap.io": "démarrage du flux audio impossible (%@)",
        ],
    ]
}
