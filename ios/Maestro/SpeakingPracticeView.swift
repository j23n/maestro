// ⚠️ UNTESTED SCAFFOLD — the SpeechAnalyzer session code follows the
// iOS 26 API surface from documentation and WILL need adjustment during
// the Phase 0 speech spike (ios/README.md, Spike B).
//
// Read-aloud practice: show a target sentence, transcribe on-device,
// score by word alignment in the core, color per-word verdicts.

import AVFoundation
import Speech
import SwiftUI

struct SpeakingPracticeView: View {
    let bridge: CoreBridge
    /// The pack item being practised — the attempt is recorded against it,
    /// so evidence lands on the right grammar point.
    let itemId: String
    let target: String
    let evidenceJson: [[String: Any]]

    /// Optional: when absent, the deterministic alignment stands alone.
    var feedback: FeedbackService?
    var prompt: String = ""
    var level: String = "A0"

    @State private var recorder = SpeechRecorder()
    @State private var result: AlignmentResult?
    @State private var transcript = ""

    var body: some View {
        VStack(spacing: 20) {
            Text(target)
                .font(.system(.title2, design: .serif))
                .foregroundStyle(Color.mCharcoal)
                .multilineTextAlignment(.center)

            if let result {
                verdictText(result)
                    .multilineTextAlignment(.center)
                Text(String(format: "%.0f%%", result.score * 100))
                    .font(.headline)
                    .foregroundStyle(result.score >= 0.8 ? Color.mSuccess : Color.mText)
                // What the recognizer actually heard. Without it, a wrong
                // score is indistinguishable from a mis-heard one, and the
                // learner has no way to tell which.
                Text("Ho sentito: «\(transcript)»")
                    .font(.caption).foregroundStyle(Color.mTextMuted)
                    .multilineTextAlignment(.center)
                if let feedback { FeedbackPanel(feedback: feedback) }
                Button("Riprova") {
                    self.result = nil
                    self.transcript = ""
                }
            }

            switch recorder.status {
            case .preparing:
                VStack(spacing: 6) {
                    ProgressView()
                    Text("Preparo il microfono…")
                        .font(.caption).foregroundStyle(Color.mTextMuted)
                }
            case .failed(let why):
                VStack(spacing: 6) {
                    Label(why, systemImage: "mic.slash")
                        .font(.footnote).foregroundStyle(Color.mGold)
                        .multilineTextAlignment(.center)
                    Button("Riprova") { recorder.start() }
                }
            case .idle, .recording:
                Button {
                    if recorder.isRecording {
                        recorder.stop { heard in
                            transcript = heard
                            score(heard)
                        }
                    } else {
                        recorder.start()
                    }
                } label: {
                    Image(
                        systemName: recorder.isRecording
                            ? "stop.circle.fill" : "mic.circle.fill"
                    )
                    .font(.system(size: 64))
                    .foregroundStyle(recorder.isRecording ? Color.mTerracotta : Color.mSage)
                }
                .disabled(result != nil)
            }
        }
        .padding()
    }

    /// Deterministic first: the alignment scorer decides the outcome and
    /// records the evidence. The model only ever explains it afterwards.
    private func score(_ heard: String) {
        let aligned = bridge.alignSpeech(target: target, transcript: heard)
        result = aligned
        try? bridge.recordAttempt(
            itemId: itemId,
            outcome: aligned.score >= 0.8
                ? "correct" : aligned.score >= 0.5 ? "partial" : "incorrect",
            modality: "speaking",
            evidenceClass: "productive",
            evidenceJson: evidenceJson,
            response: heard)

        guard let feedback, !heard.isEmpty else { return }
        let summary = aligned.verdicts
            .map { "\($0.target):\($0.status)" }
            .joined(separator: " ")
        Task {
            await feedback.request(
                kind: "speaking_feedback",
                itemId: itemId,
                submission: heard,
                variables: [
                    "level": level,
                    "prompt": prompt,
                    "target_text": target,
                    "submission": heard,
                    "alignment_summary": summary,
                    "weakness_tags": "",
                ])
        }
    }

    private func verdictText(_ result: AlignmentResult) -> Text {
        result.verdicts.reduce(Text("")) { acc, verdict in
            let color: Color = switch verdict.status {
            case .matched: .mSage
            case .near: .mBlue
            case .substituted: .mGold
            case .missed: .mTerracotta
            }
            return acc + Text(verdict.target + " ").foregroundStyle(color)
        }
    }
}

@Observable
final class SpeechRecorder {
    enum Status: Equatable {
        case idle
        case preparing          // asking permission / fetching the locale model
        case recording
        case failed(String)
    }

    var status: Status = .idle
    var isRecording: Bool { status == .recording }

    private let locale = Locale(identifier: "it-IT")
    private var engine: AVAudioEngine?
    private var analyzer: SpeechAnalyzer?
    private var transcriber: SpeechTranscriber?
    private var inputBuilder: AsyncStream<AnalyzerInput>.Continuation?
    private var collector: Task<Void, Never>?
    private var transcript = ""

    /// Microphone + recognition consent, then the on-device model for the
    /// locale. All three can fail, and the learner needs to know which:
    /// "nothing happened" is the worst possible outcome here.
    private func prepare() async throws {
        guard await AVAudioApplication.requestRecordPermission() else {
            throw RecorderError.denied("Microphone access is off for Maestro.")
        }
        let speech = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        guard speech == .authorized else {
            throw RecorderError.denied("Speech recognition access is off for Maestro.")
        }

        let transcriber = SpeechTranscriber(
            locale: locale,
            transcriptionOptions: [],
            reportingOptions: [],
            attributeOptions: [])
        // The Italian model is a download, not a given. Without this the
        // analyzer starts and simply never returns anything.
        if let request = try await AssetInventory.assetInstallationRequest(
            supporting: [transcriber])
        {
            try await request.downloadAndInstall()
        }
        self.transcriber = transcriber
    }

    func start() {
        guard status == .idle || status.isFailure else { return }
        status = .preparing
        transcript = ""
        collector = Task {
            do {
                try await prepare()
                guard let transcriber else { return }
                let analyzer = SpeechAnalyzer(modules: [transcriber])
                let (inputSequence, builder) = AsyncStream<AnalyzerInput>.makeStream()
                self.analyzer = analyzer
                self.inputBuilder = builder

                // Recording needs the session in the right category, or the
                // tap delivers silence on a real device.
                let session = AVAudioSession.sharedInstance()
                try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers])
                try session.setActive(true, options: .notifyOthersOnDeactivation)

                let engine = AVAudioEngine()
                self.engine = engine
                engine.inputNode.installTap(
                    onBus: 0, bufferSize: 4096,
                    format: engine.inputNode.outputFormat(forBus: 0)
                ) { buffer, _ in
                    builder.yield(AnalyzerInput(buffer: buffer))
                }
                try engine.start()
                try await analyzer.start(inputSequence: inputSequence)
                status = .recording

                for try await result in transcriber.results where result.isFinal {
                    transcript += String(result.text.characters) + " "
                }
            } catch is CancellationError {
                // stop() cancels the collector once the analyzer has drained.
            } catch let error as RecorderError {
                status = .failed(error.message)
                teardown()
            } catch {
                status = .failed("Couldn't start recording: \(error.localizedDescription)")
                teardown()
            }
        }
    }

    /// Stop cleanly: close the input, let the analyzer finish what it
    /// already heard, THEN read the transcript. Cancelling first (as the
    /// first draft did) discards the last utterance — usually the whole
    /// answer on a one-sentence exercise.
    func stop(onFinish: @escaping (String) -> Void) {
        guard status == .recording || status == .preparing else { return }
        status = .idle
        Task {
            engine?.inputNode.removeTap(onBus: 0)
            engine?.stop()
            inputBuilder?.finish()
            try? await analyzer?.finalizeAndFinishThroughEndOfInput()
            await collector?.value
            teardown()
            onFinish(transcript.trimmingCharacters(in: .whitespacesAndNewlines))
        }
    }

    private func teardown() {
        collector?.cancel()
        collector = nil
        engine = nil
        analyzer = nil
        inputBuilder = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    enum RecorderError: Error {
        case denied(String)
        var message: String {
            switch self { case .denied(let m): return m }
        }
    }
}

extension SpeechRecorder.Status {
    var isFailure: Bool { if case .failed = self { return true }; return false }
    var message: String? { if case .failed(let m) = self { return m }; return nil }
}
