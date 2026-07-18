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
    let target: String
    let evidenceJson: [[String: Any]]

    @State private var recorder = SpeechRecorder()
    @State private var result: AlignmentResult?

    var body: some View {
        VStack(spacing: 20) {
            Text(target).font(.title2).multilineTextAlignment(.center)

            if let result {
                verdictText(result)
                Text(String(format: "%.0f%%", result.score * 100)).font(.headline)
                Button("Riprova") { self.result = nil }
            }

            Button {
                if recorder.isRecording {
                    recorder.stop { transcript in
                        let aligned = bridge.alignSpeech(
                            target: target, transcript: transcript)
                        result = aligned
                        try? bridge.recordAttempt(
                            itemId: "speaking.read_aloud",
                            outcome: aligned.score >= 0.8 ? "correct"
                                : aligned.score >= 0.5 ? "partial" : "incorrect",
                            modality: "speaking",
                            evidenceClass: "productive",
                            evidenceJson: evidenceJson,
                            response: transcript)
                    }
                } else {
                    recorder.start()
                }
            } label: {
                Image(systemName: recorder.isRecording ? "stop.circle.fill" : "mic.circle.fill")
                    .font(.system(size: 64))
            }
        }
        .padding()
    }

    private func verdictText(_ result: AlignmentResult) -> Text {
        result.verdicts.reduce(Text("")) { acc, verdict in
            let color: Color = switch verdict.status {
            case .matched: .green
            case .near: .teal
            case .substituted: .orange
            case .missed: .red
            }
            return acc + Text(verdict.target + " ").foregroundStyle(color)
        }
    }
}

@Observable
final class SpeechRecorder {
    var isRecording = false
    private var task: Task<Void, Never>?
    private var finalTranscript = ""
    private var onFinish: ((String) -> Void)?

    func start() {
        isRecording = true
        finalTranscript = ""
        task = Task {
            do {
                // iOS 26 SpeechAnalyzer path (it-IT, on-device).
                let transcriber = SpeechTranscriber(
                    locale: Locale(identifier: "it-IT"),
                    transcriptionOptions: [],
                    reportingOptions: [],
                    attributeOptions: [])
                let analyzer = SpeechAnalyzer(modules: [transcriber])
                let (inputSequence, inputBuilder) = AsyncStream<AnalyzerInput>.makeStream()

                let engine = AVAudioEngine()
                engine.inputNode.installTap(
                    onBus: 0, bufferSize: 4096,
                    format: engine.inputNode.outputFormat(forBus: 0)
                ) { buffer, _ in
                    inputBuilder.yield(AnalyzerInput(buffer: buffer))
                }
                try engine.start()
                try await analyzer.start(inputSequence: inputSequence)

                for try await result in transcriber.results where result.isFinal {
                    finalTranscript += String(result.text.characters) + " "
                }
                engine.stop()
            } catch {
                finalTranscript = ""
            }
        }
    }

    func stop(onFinish: @escaping (String) -> Void) {
        isRecording = false
        task?.cancel()
        // Give the final results a moment to land, then hand off.
        Task {
            try? await Task.sleep(for: .milliseconds(300))
            onFinish(finalTranscript.trimmingCharacters(in: .whitespaces))
        }
    }
}
