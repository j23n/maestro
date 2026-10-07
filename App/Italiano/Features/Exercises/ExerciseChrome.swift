import LearningCore
import SwiftUI

/// A `FeedbackPresentation` as the panel with its buttons (docs/06 § Shared player behaviour). Every exercise view
/// shows feedback through this, so the copy, order and shortcuts of Show answer / Try again / Continue never drift.
struct PresentedFeedback: View {
    let presentation: FeedbackPresentation
    var onShowAnswer: () -> Void = {}
    var onTryAgain: () -> Void = {}
    let onContinue: () -> Void

    var body: some View {
        let p = presentation
        FeedbackPanel(tone: tone, headline: p.headline, detail: detail) {
            HStack(spacing: Tokens.Space.m) {
                if p.canShowAnswer {
                    Button("Show answer", action: onShowAnswer)
                        .buttonStyle(.dsSecondary)
                        .keyboardShortcut("a", modifiers: [.command, .shift])
                        .accessibilityIdentifier("feedback.showAnswer")
                }
                if p.canTryAgain {
                    Button("Try again", action: onTryAgain)
                        .buttonStyle(.dsPrimary)
                        .keyboardShortcut(.return, modifiers: [])
                        .accessibilityIdentifier("feedback.tryAgain")
                }
                if p.canContinue {
                    Button("Continue", action: onContinue)
                        .buttonStyle(.dsPrimary)
                        .keyboardShortcut(.return, modifiers: [])
                        .accessibilityIdentifier("feedback.continue")
                }
            }
        }
    }

    private var tone: FeedbackTone {
        switch presentation.tone {
        case .success: .success
        case .hint: .hint
        case .answer: .answer
        }
    }

    private var detail: String? {
        let parts = [presentation.detail, presentation.answer.map { "*\($0)*" }, presentation.rule].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: "\n")
    }
}

/// The Continue button for formats that end without a panel (assessments, listen-and-repeat, match).
struct ContinueButton: View {
    let action: () -> Void

    var body: some View {
        Button("Continue", action: action)
            .buttonStyle(.dsPrimary)
            .keyboardShortcut(.return, modifiers: [])
            .accessibilityIdentifier("feedback.continue")
    }
}

/// The small English instruction above an exercise ("Complete the sentence", "Listen and write what you hear").
struct ExerciseInstruction: View {
    let text: String

    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
    }
}

/// An Italian line with its speaker button when the pack has audio for it.
struct ItalianPromptLine: View {
    let text: TokenizedText
    let audioID: AudioID?
    let audio: ExerciseAudio
    var style: TypeStyle = Tokens.TypeScale.exercise
    var identifier = "prompt.play"

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Tokens.Space.s) {
            ItalianText(text.text, style: style)
            if audio.canPlay(audioID) {
                SpeakerButton(isPlaying: audio.isPlaying(audioID), action: { audio.toggle(audioID) },
                              identifier: identifier)
            }
        }
    }
}
