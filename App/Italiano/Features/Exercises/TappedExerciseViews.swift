import LearningCore
import SwiftUI

// The tapped and listening formats (docs/06 §§ Building-block formats, 8–11; `Pairs.png`, `Dictation.png`). Each
// view renders its view model and forwards taps; grading, attempts and hints live in the models (TappedExerciseModels).

// MARK: - Choice, true-false, sound pairs

struct ChoiceExerciseView: View {
    let model: ChoiceModel
    let audio: ExerciseAudio
    /// The `source` text shown above the question, resolved by the player.
    var source: TokenizedText?
    let onContinue: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
            header
            options
            if let hint = model.hint, !model.isDone {
                FeedbackPanel(tone: .hint, headline: "Not quite.", detail: hint) { EmptyView() }
            }
            if model.isDone { outcome }
        }
        .readableColumn()
    }

    @ViewBuilder private var header: some View {
        switch model.payload.body {
        case .choice(let c):
            VStack(alignment: .leading, spacing: Tokens.Space.l) {
                if let source { Card { ItalianText(source.text) } }
                if let it = c.promptIt {
                    ItalianPromptLine(text: it, audioID: c.promptAudioId, audio: audio, identifier: "choice.play")
                }
                if let hidden = audio.audioID(forText: c.audioTextId) {
                    HStack {
                        Spacer()
                        BigPlayButton(isPlaying: audio.isPlaying(hidden), action: { play(hidden, cap: c.plays) },
                                      identifier: "choice.listen")
                            .disabled(!canPlay(hidden, cap: c.plays))
                        Spacer()
                    }
                }
                Text(c.questionEn).dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
                    .accessibilityIdentifier("choice.question")
            }
        case .trueFalse(let t):
            VStack(alignment: .leading, spacing: Tokens.Space.l) {
                if let source { Card { ItalianText(source.text) } }
                if let hidden = audio.audioID(forText: t.audioTextId) {
                    HStack {
                        Spacer()
                        BigPlayButton(isPlaying: audio.isPlaying(hidden), action: { play(hidden, cap: t.plays) },
                                      identifier: "tf.listen")
                            .disabled(!canPlay(hidden, cap: t.plays))
                        Spacer()
                    }
                }
                ExerciseInstruction("True or false?")
                Text(t.statementEn).dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
                    .accessibilityIdentifier("tf.statement")
            }
        case .soundPair(let s):
            VStack(spacing: Tokens.Space.xxl) {
                if let tip = s.tipEn {
                    HStack(alignment: .top, spacing: Tokens.Space.l) {
                        Mascot(pose: .think, size: 56, decorative: true, isHint: true)
                        Text(tip).dsFont(Tokens.TypeScale.translation).italic().foregroundStyle(Color.ds.secondary)
                        Spacer(minLength: 0)
                    }
                }
                Text(s.question == .whichWord ? "Which word do you hear?" : "Single or double consonant?")
                    .dsFont(Tokens.TypeScale.screenTitle)
                    .foregroundStyle(Color.ds.ink)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity)
                let clip = soundPairClip(s)
                BigPlayButton(isPlaying: audio.isPlaying(clip), action: { audio.play(clip) }, identifier: "pairs.play")
                    .disabled(!audio.canPlay(clip))
            }
        default:
            EmptyView()
        }
    }

    @ViewBuilder private var options: some View {
        let isPairLayout: Bool = {
            if case .choice = model.payload.body { return false }
            return true
        }()
        let layout = isPairLayout
            ? AnyLayout(HStackLayout(spacing: Tokens.Space.l)) : AnyLayout(VStackLayout(spacing: Tokens.Space.m))
        layout {
            ForEach(Array(model.options.enumerated()), id: \.element.id) { position, option in
                OptionCard(title: option.text, subtitle: gloss(for: option), titleIsItalian: isItalian(option),
                           isSelected: model.selected == option.id, mark: mark(option)) {
                    model.select(option.id)
                }
                .disabled(model.isDone || model.markedWrong.contains(option.id))
                .modifier(NumberKey(position: position))
                .accessibilityIdentifier(identifier(for: option))
            }
        }
    }

    @ViewBuilder private var outcome: some View {
        if model.machine.isSingleAttempt {
            ContinueButton(action: onContinue)
        } else if case .done(let result) = model.machine.state {
            let success = result == .success || result == .successAfterHint || result == .successWithCorrection
            PresentedFeedback(
                presentation: FeedbackPresentation(
                    tone: success ? .success : .answer,
                    headline: success ? FeedbackCopy.success : FeedbackCopy.failedTwice,
                    detail: nil, answer: success ? nil : model.options.first { $0.id == model.correctIndex }?.text,
                    rule: success ? nil : model.payload.rule, canTryAgain: false, canShowAnswer: false,
                    canContinue: true),
                onContinue: onContinue)
        }
    }

    private func mark(_ option: ChoiceOption) -> OptionCard.Mark {
        switch model.mark(for: option) {
        case .idle: .idle
        case .correct: .correct
        case .wrong: .wrong
        }
    }

    private func isItalian(_ option: ChoiceOption) -> Bool {
        if option.italian != nil { return true }
        if case .soundPair(let s) = model.payload.body { return s.question == .whichWord }
        return false
    }

    private func gloss(for option: ChoiceOption) -> String? {
        guard case .soundPair(let s) = model.payload.body, s.question == .whichWord else { return nil }
        return s.pair?[safe: option.id]?.gloss
    }

    private func identifier(for option: ChoiceOption) -> String {
        switch model.payload.body {
        case .trueFalse: option.id == 0 ? "tf.true" : "tf.false"
        case .soundPair: "pairs.option.\(option.id)"
        default: "choice.option.\(option.id)"
        }
    }

    private func soundPairClip(_ s: ExerciseBody.SoundPair) -> AudioID? {
        switch s.question {
        case .whichWord: s.play.flatMap { s.pair?[safe: $0]?.audioId }
        case .singleOrDouble: s.word?.audioId
        }
    }

    private func canPlay(_ id: AudioID, cap: Int?) -> Bool { cap.map { audio.plays(of: id) < $0 } ?? true }

    private func play(_ id: AudioID, cap: Int?) {
        if audio.isPlaying(id) { audio.stop() } else if canPlay(id, cap: cap) { audio.play(id) }
    }
}

/// Keys 1–6 choose options on Mac and hardware keyboards (docs/06 § Shared player behaviour).
private struct NumberKey: ViewModifier {
    let position: Int

    func body(content: Content) -> some View {
        if position < 6 {
            content.keyboardShortcut(KeyEquivalent(Character(String(position + 1))), modifiers: [])
        } else {
            content
        }
    }
}

// MARK: - Match

struct MatchExerciseView: View {
    let model: MatchModel
    let audio: ExerciseAudio
    let onContinue: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
            ExerciseInstruction(isAssessment ? "Match the pairs, then check" : "Tap the matching pairs")
            HStack(alignment: .top, spacing: Tokens.Space.l) {
                VStack(spacing: Tokens.Space.m) {
                    ForEach(Array(model.leftOrder.enumerated()), id: \.element) { position, i in
                        MatchTile(state: leftState(i), action: { tapLeft(i) }) {
                            ItalianText(model.pairs[i].left.text, style: Tokens.TypeScale.answerInput)
                        }
                        .modifier(NumberKey(position: position))
                        .accessibilityIdentifier("match.left.\(i)")
                    }
                }
                VStack(spacing: Tokens.Space.m) {
                    ForEach(model.rightOrder, id: \.self) { j in
                        MatchTile(state: rightState(j), action: { model.tapRight(j) }) {
                            Text(model.pairs[j].right).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                        }
                        .accessibilityIdentifier("match.right.\(j)")
                    }
                }
            }
            if isAssessment && !model.isDone {
                Button("Check") { model.submitAssessment() }
                    .buttonStyle(.dsPrimary)
                    .disabled(model.assessmentPicks.count < model.pairs.count)
                    .keyboardShortcut(.return, modifiers: [])
                    .accessibilityIdentifier("answer.check")
            }
            if model.isDone { ContinueButton(action: onContinue) }
        }
        .readableColumn()
    }

    private var isAssessment: Bool { model.isAssessment }

    private func tapLeft(_ i: Int) {
        model.tapLeft(i)
        if !isAssessment { audio.play(model.pairs[i].leftAudioId) }
    }

    private func leftState(_ i: Int) -> MatchTileState {
        if model.locked[i] != nil { return .matched }
        if model.lastWrong?.left == i { return .wrong }
        if model.selectedLeft == i { return .selected }
        if model.assessmentPicks[i] != nil { return .paired(pairNumber(left: i)) }
        return .idle
    }

    private func rightState(_ j: Int) -> MatchTileState {
        if model.locked.values.contains(j) { return .matched }
        if model.lastWrong?.right == j { return .wrong }
        if let i = model.assessmentPicks.first(where: { $0.value == j })?.key { return .paired(pairNumber(left: i)) }
        return .idle
    }

    /// Check mode shows each pairing as a small number so the learner can see and change it (no right/wrong).
    private func pairNumber(left i: Int) -> Int { (model.leftOrder.firstIndex(of: i) ?? 0) + 1 }
}

enum MatchTileState: Equatable { case idle, selected, matched, wrong, paired(Int) }

struct MatchTile<Label: View>: View {
    let state: MatchTileState
    let action: () -> Void
    @ViewBuilder var label: Label

    var body: some View {
        Button(action: action) {
            HStack {
                label
                Spacer(minLength: 0)
                if case .paired(let n) = state {
                    Text("\(n)").dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.accent)
                }
            }
            .padding(.horizontal, Tokens.Space.l)
            .frame(maxWidth: .infinity, minHeight: Tokens.Size.inputHeight)
            .background(RoundedRectangle(cornerRadius: Tokens.Radius.tile).fill(fill))
            .overlay(RoundedRectangle(cornerRadius: Tokens.Radius.tile).strokeBorder(border, lineWidth: width))
        }
        .buttonStyle(.plain)
        .disabled(state == .matched)
        .accessibilityAddTraits(state == .selected ? .isSelected : [])
        .accessibilityValue(Text(accessibilityValue))
    }

    private var fill: Color {
        switch state {
        case .matched: Color.ds.accentTint
        case .wrong: Color.ds.warningInputBackground
        case .selected, .paired: Color.ds.accentTint
        case .idle: Color.ds.background
        }
    }

    private var border: Color {
        switch state {
        case .matched: Color.ds.success
        case .wrong: Color.ds.warning
        case .selected, .paired: Color.ds.accent
        case .idle: Color.ds.inputBorder
        }
    }

    private var width: Double { state == .idle ? Tokens.Border.control : Tokens.Border.inputError }

    private var accessibilityValue: String {
        switch state {
        case .matched: "Matched"
        case .wrong: "Not a pair"
        case .selected: "Selected"
        case .paired(let n): "Pair \(n)"
        case .idle: ""
        }
    }
}

// MARK: - Sentence building

struct SentenceBuildingView: View {
    let model: SentenceBuildingModel
    let audio: ExerciseAudio
    let onContinue: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
            ExerciseInstruction("Put the words in order")
            if case .sentenceBuilding(let s) = model.payload.body {
                Text(s.promptEn).dsFont(Tokens.TypeScale.exercise).italic().foregroundStyle(Color.ds.ink)
            }
            answerLine
            FlowLayout {
                ForEach(model.tiles) { tile in
                    let placed = !model.available.contains(tile)
                    Button { model.place(tile.id) } label: { WordTile(word: tile.word, isPlaced: placed) }
                        .buttonStyle(.plain)
                        .disabled(placed || model.isDone)
                        .accessibilityLabel(Text(tile.word))
                        .accessibilityIdentifier("build.tile.\(tile.id)")
                }
            }
            if let p = presentation {
                PresentedFeedback(presentation: p, onShowAnswer: { model.showAnswer() },
                                  onTryAgain: { removeMisplaced() }, onContinue: onContinue)
            } else if model.isDone {
                ContinueButton(action: onContinue)
            } else {
                Button("Check") { model.check() }
                    .buttonStyle(.dsPrimary)
                    .disabled(model.answerLine.isEmpty)
                    .keyboardShortcut(.return, modifiers: [])
                    .accessibilityIdentifier("answer.check")
            }
        }
        .readableColumn()
    }

    private var answerLine: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.s) {
            if model.isDone && model.lastResult?.answer.outcome.isSuccess == true {
                ItalianText(model.displayedSentence, style: Tokens.TypeScale.exercise)
            } else {
                FlowLayout {
                    ForEach(model.answerLine) { tile in
                        Button { model.remove(tile.id) } label: {
                            WordTile(word: tile.word, isMarked: model.highlighted == tile.id)
                        }
                        .buttonStyle(.plain)
                        .disabled(model.isDone)
                        .accessibilityLabel(Text(tile.word))
                        .accessibilityHint(Text("Removes the word"))
                        .accessibilityAction(named: Text("Move left")) { model.move(tile.id, by: -1) }
                        .accessibilityAction(named: Text("Move right")) { model.move(tile.id, by: 1) }
                    }
                }
                .frame(maxWidth: .infinity, minHeight: 56, alignment: .topLeading)
            }
            Rectangle().fill(Color.ds.divider).frame(height: Tokens.Border.hairline)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("build.answer")
    }

    private var presentation: FeedbackPresentation? {
        MachineFeedback.presentation(
            state: model.machine.state, context: model.machine.context, answer: model.modelAnswer,
            rule: model.payload.rule,
            hintHeadline: "Not quite. Check the order.", canShowAnswer: model.machine.canShowAnswer)
    }

    /// Try again: the misplaced tiles go back so the learner rebuilds from the first wrong word.
    private func removeMisplaced() {
        guard let first = model.highlighted, let i = model.answerLine.firstIndex(where: { $0.id == first }) else {
            return
        }
        for tile in model.answerLine[i...] { model.remove(tile.id) }
    }
}

// MARK: - Dictation

struct DictationView: View {
    @Bindable var model: DictationModel
    let audio: ExerciseAudio
    var sourceLabel: String?
    let onContinue: () -> Void
    @FocusState private var fieldFocused: Bool

    var body: some View {
        VStack(spacing: Tokens.Space.xxl) {
            VStack(spacing: Tokens.Space.l) {
                ExerciseInstruction("Listen and write what you hear")
                BigPlayButton(isPlaying: audio.isPlaying(model.audioID), action: { play(rate: 1) },
                              identifier: "dictation.play")
                    .disabled(!model.canPlay && !audio.isPlaying(model.audioID))
                if model.offersSlower {
                    Button("Play slower") { play(rate: PlaybackRate.slower) }
                        .buttonStyle(.dsSecondarySmall)
                        .disabled(!model.canPlay)
                        .accessibilityIdentifier("dictation.slower")
                }
                Text([model.hintLine, sourceLabel].compactMap { $0 }.joined(separator: " · "))
                    .dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
            }
            .frame(maxWidth: .infinity)
            VStack(alignment: .leading, spacing: Tokens.Space.m) {
                Text("What you heard").dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.secondary)
                if let result = model.result, model.isDone || presentation != nil {
                    DictationDiff(result: result)
                } else {
                    AnswerField(text: $model.response, onSubmit: { model.check() }, focus: $fieldFocused)
                    AccentKeys { model.insert($0) }
                }
            }
            if let note = model.doublingNote, presentation != nil {
                Text(note).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.warningText)
            }
            if let p = presentation {
                PresentedFeedback(presentation: p, onShowAnswer: {}, onTryAgain: {
                    model.tryAgain()
                    fieldFocused = true
                }, onContinue: onContinue)
            } else if model.isDone {
                ContinueButton(action: onContinue)
            } else {
                Button("Check") { model.check() }
                    .buttonStyle(.dsPrimary)
                    .disabled(model.response.trimmingCharacters(in: .whitespaces).isEmpty)
                    .keyboardShortcut(.return, modifiers: [])
                    .accessibilityIdentifier("answer.check")
            }
        }
        .readableColumn()
    }

    private var presentation: FeedbackPresentation? {
        MachineFeedback.presentation(
            state: model.machine.state, context: model.machine.context, answer: model.say.text, rule: nil,
            hintHeadline: "Close. Listen again.", canShowAnswer: false)
    }

    private func play(rate: Double) {
        if audio.isPlaying(model.audioID) {
            audio.stop()
        } else if model.canPlay, audio.play(model.audioID, rate: rate) {
            model.didPlay()
        }
    }
}

/// The word-by-word result after Check: correct words in ink, slips underlined in the warning colour with what was
/// typed, missing words struck through.
struct DictationDiff: View {
    let result: DictationGrader.Result

    var body: some View {
        FlowLayout(spacing: Tokens.Space.s, lineSpacing: Tokens.Space.xs) {
            ForEach(Array(result.words.enumerated()), id: \.offset) { _, word in
                VStack(alignment: .leading, spacing: 0) {
                    ItalianText(word.expected, style: Tokens.TypeScale.answerInput)
                        .underline(word.mark != .correct, color: Color.ds.warning)
                    if word.mark != .correct {
                        Text(word.typed ?? "—").dsFont(Tokens.TypeScale.uiCaption)
                            .foregroundStyle(Color.ds.warningText)
                            .strikethrough(word.typed != nil)
                    }
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(Text(label(word)))
            }
        }
        .accessibilityIdentifier("dictation.diff")
    }

    private func label(_ w: DictationGrader.Word) -> String {
        switch w.mark {
        case .correct: w.expected
        case .accent: "\(w.expected), check the accent"
        case .doubling: "\(w.expected), check the double letter"
        case .typo: "\(w.expected), small spelling slip"
        case .wrong: w.typed.map { "\(w.expected), you wrote \($0)" } ?? "\(w.expected), missing"
        }
    }
}

// MARK: - Repeat after me

struct RepeatView: View {
    let model: RepeatModel
    let audio: ExerciseAudio
    let speech: SpeechCapture
    let onContinue: () -> Void

    var body: some View {
        VStack(spacing: Tokens.Space.xxl) {
            ExerciseInstruction(model.isListenOnly ? "Listen, then say it aloud" : "Listen, then say it")
            ItalianPromptLine(text: model.say, audioID: model.audioID, audio: audio, identifier: "repeat.play")
            if model.isListenOnly {
                ContinueButton { model.finish(); onContinue() }
            } else {
                mic
                transcript
                buttons
            }
        }
        .readableColumn()
        .onAppear { audio.play(model.audioID) }
    }

    private var mic: some View {
        Button {
            if speech.isListening {
                speech.stop()
            } else {
                audio.stop()
                Task {
                    if let result = await speech.capture(expected: [model.say.text]) { model.submit(result) }
                }
            }
        } label: {
            Image(systemName: speech.isListening ? "stop.fill" : "mic.fill")
                .font(.system(size: 34, weight: .semibold))
                .foregroundStyle(Color.ds.onAccent)
                .frame(width: Tokens.Size.bigPlayButton, height: Tokens.Size.bigPlayButton)
                .background(Circle().fill(Color.ds.accent))
        }
        .buttonStyle(.plain)
        .disabled(model.isDone)
        .accessibilityLabel(Text(speech.isListening ? "Stop recording" : "Record"))
        .accessibilityIdentifier("repeat.mic")
    }

    @ViewBuilder private var transcript: some View {
        if speech.isListening {
            Text(speech.liveTranscript.isEmpty ? "Listening…" : speech.liveTranscript)
                .dsFont(Tokens.TypeScale.italianBody).foregroundStyle(Color.ds.secondary)
                .accessibilityIdentifier("repeat.transcript")
        } else if let heard = model.heard {
            VStack(spacing: Tokens.Space.s) {
                Text(model.passed == true ? "That's it." : "Not quite.")
                    .dsFont(Tokens.TypeScale.uiTitle)
                    .foregroundStyle(model.passed == true ? Color.ds.success : Color.ds.warningText)
                MixedText(text: "I heard: *\(heard)*", style: Tokens.TypeScale.uiBody)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("repeat.transcript")
        } else if let failure = speech.failureMessage {
            Text(failure).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.warningText)
                .accessibilityIdentifier("repeat.transcript")
        }
    }

    @ViewBuilder private var buttons: some View {
        if model.isDone {
            ContinueButton(action: onContinue)
        } else {
            VStack(spacing: Tokens.Space.m) {
                if model.heard != nil {
                    Button("Hear it again") { audio.play(model.audioID) }
                        .buttonStyle(.dsSecondary)
                        .disabled(!audio.canPlay(model.audioID))
                        .accessibilityIdentifier("repeat.hearAgain")
                }
                if model.attempts >= 2 {
                    Button("Continue") { model.finish(); onContinue() }
                        .buttonStyle(.dsPrimary)
                        .accessibilityIdentifier("feedback.continue")
                }
                Button("Skip — can't speak now") { model.skip(); onContinue() }
                    .buttonStyle(.dsTextLink)
                    .accessibilityIdentifier("repeat.skip")
            }
        }
    }
}
