import LearningCore
import SwiftUI

/// Cloze and recall (docs/06 §6, §7; `LibroPhone.png`, `TryAgain.png`): the prompt, the answer field with accent
/// keys, Check (Return), Show a hint (⇧⌘H), Say it, and the feedback panel.
struct TypedExerciseView: View {
    @Bindable var model: TypedExerciseModel
    let payload: ExercisePayload?
    var onSayIt: (() -> Void)?
    var onContinue: () -> Void
    @FocusState private var fieldFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
            Spacer(minLength: Tokens.Space.l)
            prompt
            Spacer(minLength: Tokens.Space.l)
            if let hint = model.visibleHint, model.feedback == nil {
                Text(hint).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                    .accessibilityIdentifier("answer.hintText")
            }
            answerArea
            if let f = model.feedback {
                feedbackPanel(f)
                    .transition(.feedbackPanel(reduceMotion: reduceMotion))
            } else {
                actions
            }
        }
        .readableColumn()
        .animation(reduceMotion ? nil : .easeOut(duration: Tokens.Motion.feedbackPanelMs / 1000), value: model.feedback)
        .onAppear { fieldFocused = true }
    }

    @ViewBuilder private var prompt: some View {
        switch payload?.body {
        case .cloze(let c)?:
            VStack(alignment: .leading, spacing: Tokens.Space.m) {
                Text("Complete the sentence").dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                ClozeSentence(before: c.before, gap: model.feedback?.answer ?? "", after: c.after)
                    .accessibilityIdentifier("cloze.sentence")
                if let en = c.promptEn {
                    Text(en).dsFont(Tokens.TypeScale.translation).foregroundStyle(Color.ds.secondary)
                }
            }
        case .recall(let r)?:
            VStack(alignment: .leading, spacing: Tokens.Space.m) {
                Text("Say it in Italian").dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                if let context = r.contextIt { ItalianText(context.text) }
                Text(r.promptEn).dsFont(Tokens.TypeScale.exercise).italic().foregroundStyle(Color.ds.ink)
                    .accessibilityIdentifier("recall.prompt")
            }
        default:
            EmptyView()
        }
    }

    private var answerArea: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.m) {
            Text("Your answer").dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.secondary)
            AnswerField(text: $model.response, isError: model.feedback?.tone == .hint,
                        onSubmit: { model.check() }, focus: $fieldFocused)
            if model.feedback == nil {
                AccentKeys { model.insert($0) }
            }
        }
    }

    private var actions: some View {
        VStack(spacing: Tokens.Space.m) {
            Button("Check") { model.check() }
                .buttonStyle(.dsPrimary)
                .disabled(!model.canCheck)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("answer.check")
            HStack {
                if model.canRequestHint {
                    Button("Show a hint") { model.requestHint() }
                        .buttonStyle(.dsTextLink)
                        .keyboardShortcut("h", modifiers: [.command, .shift])
                        .accessibilityIdentifier("answer.hint")
                }
                Spacer()
                if model.canSayIt, let onSayIt {
                    Button(action: onSayIt) { Label("Say it", systemImage: "mic.fill") }
                        .buttonStyle(.dsSecondarySmall)
                        .accessibilityIdentifier("answer.sayIt")
                }
            }
        }
    }

    private func feedbackPanel(_ f: FeedbackPresentation) -> some View {
        PresentedFeedback(
            presentation: f, onShowAnswer: { model.showAnswer() },
            onTryAgain: {
                model.tryAgain()
                fieldFocused = true
            },
            onContinue: {
                if f.tone == .answer && !model.isDone { model.acknowledge() }
                onContinue()
            })
    }
}

/// The cloze sentence with a visible gap (a 2 pt ink baseline), or the answer filled in after feedback.
struct ClozeSentence: View {
    let before: TokenizedText
    let gap: String
    let after: TokenizedText

    var body: some View {
        let gapText = gap.isEmpty ? "\u{2002}\u{2002}\u{2002}\u{2002}\u{2002}\u{2002}" : gap
        (Text(ItalianText.attributed(before.text, highlight: Color.ds.accent))
            + Text(gapText).underline(true, color: Color.ds.ink).foregroundColor(Color.ds.accent)
            + Text(ItalianText.attributed(after.text, highlight: Color.ds.accent)))
            .dsFont(Tokens.TypeScale.exercise)
            .foregroundStyle(Color.ds.ink)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityElement()
            .accessibilityLabel(Text("\(before.text) blank \(after.text)"))
            .accessibilityIdentifier("cloze.gap")
    }
}
