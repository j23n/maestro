import AVFoundation
import Foundation
import Speech
import os

// The real `SpeechRecognizing` (docs/09 § Speech recognition): SpeechAnalyzer + one SpeechTranscriber (it-IT) per
// recording that gives both the live (volatile) transcript and the final alternatives; DictationTranscriber as the
// fallback with the expected answers as contextual strings. Availability is checked at runtime, the locale is
// reserved every time, and assets are downloaded with progress. Recording stops after 1.2 s of silence following
// speech, at 10 s, or on stop(). No pronunciation scoring (ADR-08).
//
// ⚠️ UNEXERCISED: written against the iOS/macOS 26 SDK documentation; M5.3 verifies every API name on a device
// (the Simulator can't run SpeechTranscriber) and records the differences in PROGRESS.md.

private let speechLogger = Logger(subsystem: "com.j23n.italian", category: "speech")

@MainActor
final class SpeechAnalyzerRecognizer: SpeechRecognizing {
    private let italian = Locale(identifier: "it-IT")
    private let speechEnabled: () -> Bool
    private var engine: AVAudioEngine?
    private var stopRequested = false

    /// `speechEnabled` reads the device setting `speech.enabled`.
    init(speechEnabled: @escaping () -> Bool) { self.speechEnabled = speechEnabled }

    func availability() async -> SpeechAvailability {
        guard speechEnabled() else { return .disabledInSettings }
        switch AVAudioApplication.shared.recordPermission {
        case .denied: return .denied
        default: break
        }
        if SpeechTranscriber.isAvailable, let locale = await SpeechTranscriber.supportedLocale(equivalentTo: italian) {
            let installed = await SpeechTranscriber.installedLocales
            return installed.contains(where: { $0.identifier(.bcp47) == locale.identifier(.bcp47) })
                ? .available : .needsDownload
        }
        if await DictationTranscriber.supportedLocale(equivalentTo: italian) != nil { return .available }
        return .unsupported
    }

    func downloadAssets(progress: @escaping @MainActor (Double) -> Void) async throws {
        guard let locale = await SpeechTranscriber.supportedLocale(equivalentTo: italian) else {
            throw SpeechError.unavailable(.unsupported)
        }
        let transcriber = makeTranscriber(locale)
        guard let request = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) else {
            progress(1)
            return  // nothing to download
        }
        let task = Task { @MainActor in
            while !Task.isCancelled {
                progress(request.progress.fractionCompleted)
                try? await Task.sleep(for: .milliseconds(200))
            }
        }
        defer { task.cancel() }
        try await request.downloadAndInstall()
        progress(1)
    }

    private func makeTranscriber(_ locale: Locale) -> SpeechTranscriber {
        // One transcriber built from options rather than presets: volatile results for the live view, plus
        // alternatives and confidence on the final result (docs/09; verify the option names in M5.3).
        SpeechTranscriber(
            locale: locale, transcriptionOptions: [], reportingOptions: [.volatileResults, .alternativeTranscriptions],
            attributeOptions: [.transcriptionConfidence])
    }

    func recognize(
        expected: [String], live: @escaping @MainActor (String) -> Void, recordingURL: URL?
    ) async throws
        -> SpeechResult
    {
        let state = await availability()
        guard state.canSpeak else { throw SpeechError.unavailable(state) }
        guard await AVAudioApplication.requestRecordPermission() else { throw SpeechError.unavailable(.denied) }
        stopRequested = false

        let module: any SpeechModule
        var transcriberResults: AsyncThrowingStream<SpeechTranscriber.Result, Error>?
        var dictationResults: AsyncThrowingStream<DictationTranscriber.Result, Error>?
        if SpeechTranscriber.isAvailable, let locale = await SpeechTranscriber.supportedLocale(equivalentTo: italian) {
            try await AssetInventory.reserve(locale: locale)  // every time, even when installed (docs/09)
            let t = makeTranscriber(locale)
            transcriberResults = AsyncThrowingStream { continuation in
                Task {
                    do {
                        for try await r in t.results { continuation.yield(r) }
                        continuation.finish()
                    } catch {
                        continuation.finish(throwing: error)
                    }
                }
            }
            module = t
        } else if let locale = await DictationTranscriber.supportedLocale(equivalentTo: italian) {
            try await AssetInventory.reserve(locale: locale)
            let d = DictationTranscriber(locale: locale, preset: .progressiveShortDictation)
            dictationResults = AsyncThrowingStream { continuation in
                Task {
                    do {
                        for try await r in d.results { continuation.yield(r) }
                        continuation.finish()
                    } catch {
                        continuation.finish(throwing: error)
                    }
                }
            }
            module = d
        } else {
            throw SpeechError.unavailable(.unsupported)
        }

        let analyzer = SpeechAnalyzer(modules: [module])
        if dictationResults != nil, !expected.isEmpty {
            let context = AnalysisContext()
            context.contextualStrings[.general] = Array(expected.prefix(100))
            try await analyzer.setContext(context)
        }
        guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [module]) else {
            throw SpeechError.failed("no audio format")
        }
        let (inputs, builder) = AsyncStream<AnalyzerInput>.makeStream()
        try await analyzer.start(inputSequence: inputs)

        AudioSessionConfigurator.activateForRecording()
        let engine = AVAudioEngine()
        self.engine = engine
        let input = engine.inputNode
        let inputFormat = input.outputFormat(forBus: 0)
        guard let converter = AVAudioConverter(from: inputFormat, to: format) else {
            throw SpeechError.failed("no converter")
        }
        let recorder = try recordingURL.map { try AVAudioFile(forWriting: $0, settings: Self.m4aSettings) }
        let detector = SilenceDetector()
        input.installTap(
            onBus: 0, bufferSize: 2048, format: inputFormat,
            block: Self.tapBlock(
                recorder: recorder, detector: detector, converter: converter, format: format, builder: builder))
        engine.prepare()
        try engine.start()

        // Stop on silence after speech, on the 10 s limit, or when stop() is called.
        let started = ContinuousClock.now
        let watcher = Task { @MainActor in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(100))
                let elapsed = ContinuousClock.now - started
                if self.stopRequested || detector.silentAfterSpeech(seconds: RecordingLimits.silenceAfterSpeechSeconds)
                    || elapsed >= .seconds(RecordingLimits.maximumSeconds)
                {
                    break
                }
            }
            input.removeTap(onBus: 0)
            engine.stop()
            builder.finish()
            try? await analyzer.finalizeAndFinishThroughEndOfInput()
        }
        defer { watcher.cancel() }

        var final = ""
        var alternatives: [String] = []
        var confidence: Double?
        if let stream = transcriberResults {
            for try await result in stream {
                let text = String(result.text.characters)
                live(final + text)
                if result.isFinal {
                    final += text
                    alternatives = result.alternatives.map { String($0.characters) }
                    confidence = result.text.runs.compactMap { $0.transcriptionConfidence }.min()
                }
            }
        } else if let stream = dictationResults {
            for try await result in stream {
                let text = String(result.text.characters)
                live(final + text)
                if result.isFinal {
                    final += text
                    alternatives = result.alternatives.map { String($0.characters) }
                }
            }
        }
        _ = await watcher.value
        self.engine = nil
        let transcript = final.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty else { throw SpeechError.nothingHeard }
        return SpeechResult(transcript: transcript, alternatives: alternatives, confidence: confidence)
    }

    func stop() { stopRequested = true }

    private static let m4aSettings: [String: Any] = [
        AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 24_000, AVNumberOfChannelsKey: 1,
        AVEncoderBitRateKey: 48_000,
    ]

    /// The input tap runs on the audio thread. Built here, outside the main actor: a closure written inside
    /// `recognize` would be main-actor isolated, and Swift 6 traps when AVAudioEngine calls it off the main thread.
    private nonisolated static func tapBlock(
        recorder: AVAudioFile?, detector: SilenceDetector, converter: AVAudioConverter, format: AVAudioFormat,
        builder: AsyncStream<AnalyzerInput>.Continuation
    ) -> AVAudioNodeTapBlock {
        { buffer, _ in
            try? recorder?.write(from: buffer)
            detector.feed(buffer)
            if let converted = Self.convert(buffer, with: converter, to: format) {
                builder.yield(AnalyzerInput(buffer: converted))
            }
        }
    }

    private nonisolated static func convert(
        _ buffer: AVAudioPCMBuffer, with converter: AVAudioConverter, to format: AVAudioFormat
    ) -> AVAudioPCMBuffer? {
        let ratio = format.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 1
        guard let out = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else { return nil }
        var consumed = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if consumed {
                status.pointee = .noDataNow
                return nil
            }
            consumed = true
            status.pointee = .haveData
            return buffer
        }
        if let error {
            speechLogger.error("convert: \(error.localizedDescription, privacy: .public)")
            return nil
        }
        return out
    }
}

/// Energy-threshold silence detection on the input tap (docs/09: stop after 1.2 s of silence following speech).
final class SilenceDetector: @unchecked Sendable {
    // @unchecked: written from the audio tap thread and read from the main actor, guarded by `lock`.
    private let lock = NSLock()
    private var heardSpeech = false
    private var lastLoud = ContinuousClock.now
    private let threshold: Float = 0.02  // RMS; tune from the M5.3 device recordings

    func feed(_ buffer: AVAudioPCMBuffer) {
        guard let data = buffer.floatChannelData?[0], buffer.frameLength > 0 else { return }
        var sum: Float = 0
        for i in 0..<Int(buffer.frameLength) { sum += data[i] * data[i] }
        let rms = (sum / Float(buffer.frameLength)).squareRoot()
        lock.withLock {
            if rms > threshold {
                heardSpeech = true
                lastLoud = .now
            }
        }
    }

    func silentAfterSpeech(seconds: Double) -> Bool {
        lock.withLock { heardSpeech && ContinuousClock.now - lastLoud >= .milliseconds(Int(seconds * 1000)) }
    }
}
