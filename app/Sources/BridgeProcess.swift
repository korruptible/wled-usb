import Foundation

final class BridgeProcess {
    enum State {
        case stopped
        case running
        case failed(String)
    }

    private(set) var state: State = .stopped
    private(set) var lines: [String] = []
    private var process: Process?
    private var input: FileHandle?
    private let port: Int
    private let onChange: () -> Void

    var url: URL { URL(string: "http://127.0.0.1:\(port)/")! }

    init(port: Int = 8723, onChange: @escaping () -> Void) {
        self.port = port
        self.onChange = onChange
    }

    private static var resources: URL {
        Bundle.main.resourceURL ?? URL(fileURLWithPath: ".")
    }

    private static var support: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory,
                                            in: .userDomainMask)[0]
            .appendingPathComponent("WLED USB", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base
    }

    func start() {
        guard process == nil else { return }

        let python = Self.resources.appendingPathComponent("python/bin/python3")
        let bridge = Self.resources.appendingPathComponent("bridge")
        let support = Self.support

        let task = Process()
        task.executableURL = python
        task.currentDirectoryURL = bridge
        task.arguments = [
            "-u", "-m", "wled_usb",
            "--http-port", String(port),
            "--audio-stdin",
            "--presets", support.appendingPathComponent("presets.json").path,
            "--notifications", support.appendingPathComponent("notifications.json").path,
            "--audio-config", support.appendingPathComponent("audio.json").path,
        ]
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = bridge.path
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        task.environment = environment

        let feed = Pipe()
        task.standardInput = feed

        let output = Pipe()
        task.standardOutput = output
        task.standardError = output
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            guard !chunk.isEmpty, let text = String(data: chunk, encoding: .utf8) else { return }
            DispatchQueue.main.async { self?.absorb(text) }
        }

        task.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async {
                self?.process = nil
                self?.state = finished.terminationStatus == 0
                    ? .stopped
                    : .failed("le pont s'est arrêté (code \(finished.terminationStatus))")
                self?.onChange()
            }
        }

        do {
            try task.run()
            process = task
            input = feed.fileHandleForWriting
            state = .running
        } catch {
            state = .failed(error.localizedDescription)
        }
        onChange()
    }

    private func absorb(_ text: String) {
        for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
            lines.append(String(line))
        }
        if lines.count > 200 { lines.removeFirst(lines.count - 200) }
        onChange()
    }

    func send(rms: UInt8, bands: [UInt8]) {
        guard let input else { return }
        var frame = Data([0xA5, 0x5A, UInt8(bands.count), rms])
        frame.append(contentsOf: bands)
        do {
            try input.write(contentsOf: frame)
        } catch {
            self.input = nil
        }
    }

    func stop() {
        input = nil
        process?.terminate()
        process = nil
        state = .stopped
    }
}
