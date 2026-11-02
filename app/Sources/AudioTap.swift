import AudioToolbox
import Foundation

enum AudioTapError: LocalizedError {
    case unsupported
    case tapFailed(OSStatus)
    case aggregateFailed(OSStatus)
    case ioFailed(OSStatus)

    var errorDescription: String? {
        switch self {
        case .unsupported:
            return "la capture audio système demande macOS 14.2 ou plus récent"
        case .tapFailed(let status):
            return "création du tap refusée (\(status)) : autorisation « enregistrement audio du système » manquante ?"
        case .aggregateFailed(let status):
            return "création du périphérique agrégé impossible (\(status))"
        case .ioFailed(let status):
            return "démarrage du flux audio impossible (\(status))"
        }
    }
}

final class AudioTap {
    private var tapID: AUAudioObjectID = kAudioObjectUnknown
    private var deviceID: AudioObjectID = kAudioObjectUnknown
    private var procID: AudioDeviceIOProcID?
    private let onSamples: ([Float], Int, Double) -> Void

    init(onSamples: @escaping ([Float], Int, Double) -> Void) {
        self.onSamples = onSamples
    }

    func start() throws {
        guard #available(macOS 14.2, *) else { throw AudioTapError.unsupported }

        let description = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
        description.name = "WLED USB"
        description.isPrivate = true
        description.muteBehavior = .unmuted

        var status = AudioHardwareCreateProcessTap(description, &tapID)
        guard status == noErr, tapID != kAudioObjectUnknown else {
            throw AudioTapError.tapFailed(status)
        }

        let uid = description.uuid.uuidString
        let settings: [String: Any] = [
            kAudioAggregateDeviceNameKey: "WLED USB Tap",
            kAudioAggregateDeviceUIDKey: "fr.wledusb.tap.\(uid)",
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [],
            kAudioAggregateDeviceTapListKey: [[kAudioSubTapUIDKey: uid]],
        ]

        status = AudioHardwareCreateAggregateDevice(settings as CFDictionary, &deviceID)
        guard status == noErr, deviceID != kAudioObjectUnknown else {
            throw AudioTapError.aggregateFailed(status)
        }

        let rate = try nominalSampleRate()
        let handler = onSamples
        status = AudioDeviceCreateIOProcIDWithBlock(&procID, deviceID, nil) {
            _, inputData, _, _, _ in
            let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inputData))
            guard let first = buffers.first,
                  let raw = first.mData else { return }
            let count = Int(first.mDataByteSize) / MemoryLayout<Float>.size
            let samples = Array(UnsafeBufferPointer(start: raw.assumingMemoryBound(to: Float.self),
                                                    count: count))
            handler(samples, Int(first.mNumberChannels), rate)
        }
        guard status == noErr, let procID else { throw AudioTapError.ioFailed(status) }

        status = AudioDeviceStart(deviceID, procID)
        guard status == noErr else { throw AudioTapError.ioFailed(status) }
    }

    private func nominalSampleRate() throws -> Double {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyNominalSampleRate,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var rate = Double(48000)
        var size = UInt32(MemoryLayout<Double>.size)
        let status = AudioObjectGetPropertyData(deviceID, &address, 0, nil, &size, &rate)
        guard status == noErr else { throw AudioTapError.ioFailed(status) }
        return rate
    }

    func stop() {
        if let procID {
            AudioDeviceStop(deviceID, procID)
            AudioDeviceDestroyIOProcID(deviceID, procID)
            self.procID = nil
        }
        if deviceID != kAudioObjectUnknown {
            AudioHardwareDestroyAggregateDevice(deviceID)
            deviceID = kAudioObjectUnknown
        }
        if tapID != kAudioObjectUnknown {
            AudioHardwareDestroyProcessTap(tapID)
            tapID = kAudioObjectUnknown
        }
    }
}
