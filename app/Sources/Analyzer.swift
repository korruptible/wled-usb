import Accelerate

final class Analyzer {
    static let bands = 24

    private let size = 1024
    private let log2n: vDSP_Length = 10
    private let fft: vDSP.FFT<DSPSplitComplex>
    private let window: [Float]
    private var pending: [Float] = []
    private var smoothed = [Float](repeating: 0, count: Analyzer.bands)
    private let onBands: (UInt8, [UInt8]) -> Void

    init?(onBands: @escaping (UInt8, [UInt8]) -> Void) {
        guard let fft = vDSP.FFT(log2n: log2n, radix: .radix2, ofType: DSPSplitComplex.self)
        else { return nil }
        self.fft = fft
        self.window = vDSP.window(ofType: Float.self, usingSequence: .hanningDenormalized,
                                  count: size, isHalfWindow: false)
        self.onBands = onBands
    }

    func feed(_ samples: [Float], channels: Int, rate: Double) {
        if channels > 1 {
            var mono = [Float](repeating: 0, count: samples.count / channels)
            for index in 0..<mono.count {
                var sum: Float = 0
                for channel in 0..<channels { sum += samples[index * channels + channel] }
                mono[index] = sum / Float(channels)
            }
            pending += mono
        } else {
            pending += samples
        }

        while pending.count >= size {
            let frame = Array(pending[0..<size])
            pending.removeFirst(size)
            var energy: Float = 0
            vDSP_measqv(frame, 1, &energy, vDSP_Length(size))
            let rms = min(1, energy.squareRoot())
            onBands(UInt8(rms * 255), analyse(frame, rate: rate))
        }
        if pending.count > size * 8 { pending.removeFirst(pending.count - size) }
    }

    private func analyse(_ frame: [Float], rate: Double) -> [UInt8] {
        var windowed = [Float](repeating: 0, count: size)
        vDSP.multiply(frame, window, result: &windowed)

        let half = size / 2
        var real = [Float](repeating: 0, count: half)
        var imaginary = [Float](repeating: 0, count: half)
        var magnitudes = [Float](repeating: 0, count: half)

        real.withUnsafeMutableBufferPointer { realPtr in
            imaginary.withUnsafeMutableBufferPointer { imagPtr in
                var split = DSPSplitComplex(realp: realPtr.baseAddress!,
                                            imagp: imagPtr.baseAddress!)
                windowed.withUnsafeBufferPointer { input in
                    input.baseAddress!.withMemoryRebound(to: DSPComplex.self, capacity: half) {
                        vDSP_ctoz($0, 2, &split, 1, vDSP_Length(half))
                    }
                }
                fft.forward(input: split, output: &split)
                vDSP.squareMagnitudes(split, result: &magnitudes)
            }
        }

        let nyquist = Float(rate / 2)
        let lowest: Float = 40
        let highest = min(Float(14000), nyquist)
        var output = [UInt8](repeating: 0, count: Self.bands)

        for band in 0..<Self.bands {
            let from = lowest * pow(highest / lowest, Float(band) / Float(Self.bands))
            let to = lowest * pow(highest / lowest, Float(band + 1) / Float(Self.bands))
            let first = max(1, Int(from / nyquist * Float(half)))
            let last = min(half - 1, max(first, Int(to / nyquist * Float(half))))

            var peak: Float = 0
            for bin in first...last { peak = max(peak, magnitudes[bin]) }

            let power = peak / (Float(size) * Float(size))
            let decibels = power > 0 ? 10 * log10f(power) : -120
            let level = max(0, min(1, (decibels + 85) / 75))
            smoothed[band] = level > smoothed[band]
                ? level
                : smoothed[band] * 0.80 + level * 0.20
            output[band] = UInt8(smoothed[band] * 255)
        }
        return output
    }
}
