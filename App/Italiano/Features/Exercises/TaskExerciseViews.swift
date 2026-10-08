import LearningCore
import SwiftUI

// The task formats (docs/06 §§ 12–15; `Dialogue.png`): conversation, talk, guided writing and relay. Turn matching,
// goals, points and grading live in TaskExerciseModels; these views only lay them out and run the mic.

// MARK: - Conversation

struct ConversationView: View {
    @Bindable var model: ConversationModel
    let audio: ExerciseAudio
    let speech: SpeechCapture
    /// The character's display name (from the story bible), shown in small caps over their lines.
    let characterName: String
    let onContinue: () -> Void
    @State private var showEnglish = false
    @State private var typing = false
    @FocusState private var fieldFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 0) {
                    transcript.frame(minWidth: 560)
                    Divider()
                    sidePanel.frame(width: 320).padding(Tokens.Space.xxl)
                }
                VStack(spacing: 0) {
                    DisclosureGroup("Your goals (\(doneCount)/\(model.goals.count))") {
                        GoalChecklist(goals: checklist).padding(.top, Tokens.Space.s)
                    }
                    .dsFont(Tokens.TypeScale.uiCallout)
                    .padding(.horizontal, Tokens.Space.screenPaddingCompact)
                    .padding(.vertical, Tokens.Space.m)
                    transcript
                }
            }
            Divider()
            bottomBar
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(showEnglish ? "Hide English" : "Show English") { showEnglish.toggle() }
                    .buttonStyle(.dsSecondarySmall)
                    .accessibilityIdentifier("conv.english")
            }
        }
        .onAppear { playCurrentLine() }
        .onChange(of: model.nodeID) { _, _ in playCurrentLine() }
    }

    private var doneCount: Int { model.goals.filter(\.done).count }
    private var checklist: [GoalChecklist.Goal] { model.goals.map { .init(id: $0.id, text: $0.text, done: $0.done) } }

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                    ForEach(model.lines) { line in
                        lineView(line).id(line.id).accessibilityIdentifier("conv.line.\(line.id)")
                    }
                    if speech.isListening { listeningBubble }
                    feedback
                    if model.isFinished { ContinueButton(action: onContinue).padding(.top, Tokens.Space.l) }
                }
                .padding(Tokens.Space.screenPaddingCompact)
                .frame(maxWidth: Tokens.Size.readableWidth, alignment: .leading)
            }
            .onChange(of: model.lines.count) { _, _ in
                if let last = model.lines.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } }
            }
        }
    }

    private func lineView(_ line: ConversationModel.Line) -> some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xs) {
            Text(line.speaker == .character ? characterName.uppercased() : "YOU")
                .dsFont(Tokens.TypeScale.uiCaption)
                .foregroundStyle(line.speaker == .character ? Color.ds.secondary : Color.ds.accent)
            ItalianText(line.text, style: Tokens.TypeScale.storyRegular)
            if showEnglish, let en = line.english {
                Text(en).dsFont(Tokens.TypeScale.translation).foregroundStyle(Color.ds.secondary)
            }
        }
        .padding(.leading, line.speaker == .learner ? Tokens.Space.screenPaddingRegular : 0)
        .accessibilityElement(children: .combine)
    }

    private var listeningBubble: some View {
        HStack(spacing: Tokens.Space.m) {
            Image(systemName: "waveform").foregroundStyle(Color.ds.accent)
            Text(speech.liveTranscript.isEmpty ? "Listening…" : speech.liveTranscript)
                .dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
        }
        .padding(.horizontal, Tokens.Space.l)
        .padding(.vertical, Tokens.Space.m)
        .overlay(Capsule().strokeBorder(Color.ds.accent, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
        .padding(.leading, Tokens.Space.screenPaddingRegular)
        .accessibilityLabel(Text("Listening"))
    }

    @ViewBuilder private var feedback: some View {
        switch model.feedback {
        case .hint(let text)?:
            FeedbackPanel(tone: .hint, headline: "Not quite.", detail: text) { EmptyView() }
        case .youCouldSay(let phrase)?:
            FeedbackPanel(tone: .answer, headline: "You could say:", detail: "*\(phrase)*") {
                Button("Continue") { model.continueAfterMiss() }
                    .buttonStyle(.dsPrimary)
                    .accessibilityIdentifier("feedback.continue")
            }
        case nil:
            EmptyView()
        }
        if let failure = speech.failureMessage {
            Text(failure).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.warningText)
        }
    }

    private var sidePanel: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
            Text("Your goals").dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
            GoalChecklist(goals: checklist)
            if !model.helpChips.isEmpty && !model.isFinished { helpChips }
            Spacer()
        }
    }

    private var helpChips: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.m) {
            HStack(spacing: Tokens.Space.m) {
                Mascot(pose: .think, size: 56, decorative: true, isHint: true)
                Text("Stuck? You could say:").dsFont(Tokens.TypeScale.translation).italic()
                    .foregroundStyle(Color.ds.secondary)
            }
            ForEach(Array(model.helpChips.enumerated()), id: \.offset) { n, chip in
                Button {
                    model.response = chip.text
                    typing = true
                    fieldFocused = true
                } label: {
                    ItalianText(chip.text, style: Tokens.TypeScale.answerInput)
                        .padding(Tokens.Space.l)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .overlay(
                            RoundedRectangle(cornerRadius: Tokens.Radius.tile)
                                .strokeBorder(Color.ds.divider, lineWidth: Tokens.Border.hairline))
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("conv.help.\(n)")
            }
        }
    }

    @ViewBuilder private var bottomBar: some View {
        if !model.isFinished {
            VStack(spacing: Tokens.Space.m) {
                if typing && model.canType {
                    HStack(spacing: Tokens.Space.m) {
                        AnswerField(text: $model.response, onSubmit: submitTyped, focus: $fieldFocused)
                        Button("Send", action: submitTyped)
                            .buttonStyle(.dsSecondarySmall)
                            .disabled(model.response.trimmingCharacters(in: .whitespaces).isEmpty)
                            .accessibilityIdentifier("answer.check")
                    }
                    AccentKeys { model.response += $0 }
                }
                HStack(spacing: Tokens.Space.xxl) {
                    if model.canType {
                        Button(typing ? "Hide keyboard" : "Type instead") {
                            typing.toggle()
                            fieldFocused = typing
                        }
                        .buttonStyle(.dsSecondarySmall)
                        .accessibilityIdentifier("conv.type")
                    }
                    if model.canSpeak { micButton }
                    Button("Hear \(characterName) again") { playCurrentLine() }
                        .buttonStyle(.dsSecondarySmall)
                        .disabled(!audio.canPlay(model.node?.audioId))
                        .keyboardShortcut("l", modifiers: .command)
                        .accessibilityIdentifier("conv.replay")
                }
            }
            .padding(Tokens.Space.l)
            .frame(maxWidth: .infinity)
        }
    }

    private var micButton: some View {
        Button {
            if speech.isListening {
                speech.stop()
            } else {
                audio.stop()
                let expected =
                    (model.helpChips.map(\.text)
                        + (model.node?.expect.flatMap(\.accept).flatMap(\.expansions) ?? []))
                Task { if let r = await speech.capture(expected: expected) { model.submitSpoken(r) } }
            }
        } label: {
            Image(systemName: speech.isListening ? "stop.fill" : "mic.fill")
                .font(.system(size: 28, weight: .semibold))
                .foregroundStyle(Color.ds.onAccent)
                .frame(width: 72, height: 72)
                .background(Circle().fill(Color.ds.accent))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(speech.isListening ? "Stop recording" : "Speak"))
        .accessibilityIdentifier("conv.mic")
    }

    private func submitTyped() {
        model.submitTyped()
        if model.feedback == nil { model.response = "" }
    }

    private func playCurrentLine() { audio.play(model.node?.audioId) }
}

// MARK: - Talk about it

struct TalkView: View {
    @Bindable var model: TalkModel
    let audio: ExerciseAudio
    let speech: SpeechCapture
    let onContinue: () -> Void
    @State private var showingResult = false
    @FocusState private var fieldFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
            ExerciseInstruction("Talk about it")
            Text(model.talk.promptEn).dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
            pointsList
            if showingResult, model.result != nil {
                resultSection
            } else {
                answerSection
            }
        }
        .readableColumn()
    }

    private var pointsList: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.m) {
            ForEach(model.talk.points, id: \.id) { point in
                HStack(spacing: Tokens.Space.m) {
                    Image(
                        systemName: showingResult && model.found.contains(point.id)
                            ? "checkmark.circle.fill"
                            : "circle"
                    )
                    .foregroundStyle(
                        showingResult && model.found.contains(point.id)
                            ? Color.ds.success : Color.ds.inputBorder
                    )
                    .accessibilityHidden(true)
                    Text(point.en).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                }
                .accessibilityElement(children: .combine)
                .accessibilityValue(Text(showingResult ? (model.found.contains(point.id) ? "found" : "not found") : ""))
                .accessibilityIdentifier("talk.point.\(point.id)")
            }
        }
    }

    @ViewBuilder private var answerSection: some View {
        if speech.isListening {
            Text(speech.liveTranscript.isEmpty ? "Listening…" : speech.liveTranscript)
                .dsFont(Tokens.TypeScale.italianBody).foregroundStyle(Color.ds.secondary)
        }
        if let failure = speech.failureMessage {
            Text(failure).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.warningText)
        }
        if model.canType {
            AnswerField(text: $model.response, onSubmit: submitTyped, focus: $fieldFocused)
                .accessibilityIdentifier("talk.type")
            AccentKeys { model.response += $0 }
            Button("Check", action: submitTyped)
                .buttonStyle(.dsPrimary)
                .disabled(model.response.trimmingCharacters(in: .whitespaces).isEmpty)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("answer.check")
        } else {
            HStack {
                Spacer()
                Button {
                    if speech.isListening {
                        speech.stop()
                    } else {
                        Task {
                            if let r = await speech.capture(expected: [model.talk.model.text]) {
                                model.submitSpoken(r)
                                showingResult = true
                            }
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
                .accessibilityLabel(Text(speech.isListening ? "Stop recording" : "Record"))
                .accessibilityIdentifier("talk.mic")
                Spacer()
            }
        }
    }

    private var resultSection: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.l) {
            let passed = model.result?.passed == true
            FeedbackPanel(
                tone: passed ? .success : .hint,
                headline: passed ? "Nicely done." : "Try to cover a few more points.",
                detail: "I heard: *\(model.response)*"
            ) { EmptyView() }
            Card {
                VStack(alignment: .leading, spacing: Tokens.Space.s) {
                    Text("You could say").dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.secondary)
                    ItalianPromptLine(
                        text: model.talk.model, audioID: model.talk.modelAudioId, audio: audio,
                        style: Tokens.TypeScale.italianBody, identifier: "talk.model")
                }
            }
            HStack(spacing: Tokens.Space.m) {
                Button("Try again") {
                    showingResult = false
                    model.response = ""
                    speech.reset()
                }
                .buttonStyle(.dsSecondary)
                .accessibilityIdentifier("talk.tryAgain")
                ContinueButton(action: onContinue)
            }
        }
    }

    private func submitTyped() {
        guard !model.response.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        model.submitTyped()
        showingResult = true
    }
}

// MARK: - Guided writing

struct WritingView: View {
    @Bindable var model: WritingModel
    let onContinue: () -> Void
    @FocusState private var focusedField: Int?

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
            ExerciseInstruction(model.isForm ? "Fill in the form" : "Write in Italian")
            Text(model.writing.promptEn).dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
            if model.isForm { form } else { freeText }
            if model.submitted { feedback }
            if model.submitted {
                ContinueButton(action: onContinue)
            } else {
                Button("Check") { model.submit() }
                    .buttonStyle(.dsPrimary)
                    .disabled(model.isForm ? model.fieldValues.allSatisfy(\.isEmpty) : model.text.isEmpty)
                    .keyboardShortcut(.return, modifiers: .command)
                    .accessibilityIdentifier("answer.check")
            }
        }
        .readableColumn()
    }

    private var form: some View {
        Card {
            VStack(alignment: .leading, spacing: Tokens.Space.l) {
                ForEach(Array((model.writing.fields ?? []).enumerated()), id: \.offset) { n, field in
                    VStack(alignment: .leading, spacing: Tokens.Space.xs) {
                        HStack(alignment: .firstTextBaseline) {
                            ItalianText(field.labelIt.text, style: Tokens.TypeScale.italianBody)
                            Text(field.labelEn).dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.secondary)
                        }
                        TextField("", text: $model.fieldValues[n])
                            .dsFont(Tokens.TypeScale.answerInput)
                            .textFieldStyle(.roundedBorder)
                            .autocorrectionDisabled()
                            .focused($focusedField, equals: n)
                            .disabled(model.submitted)
                            .accessibilityLabel(Text(field.labelEn))
                            .accessibilityIdentifier("writing.field.\(n)")
                        if model.submitted, let valid = model.fieldValid[safe: n] ?? nil, !valid {
                            Text("Check this one.").dsFont(Tokens.TypeScale.uiCaption)
                                .foregroundStyle(Color.ds.warningText)
                        }
                    }
                }
            }
        }
    }

    private var freeText: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.s) {
            TextEditor(text: $model.text)
                .dsFont(Tokens.TypeScale.answerInput)
                .frame(minHeight: 180)
                .scrollContentBackground(.hidden)
                .padding(Tokens.Space.m)
                .background(RoundedRectangle(cornerRadius: Tokens.Radius.input).fill(Color.ds.background))
                .overlay(
                    RoundedRectangle(cornerRadius: Tokens.Radius.input)
                        .strokeBorder(Color.ds.inputBorder, lineWidth: Tokens.Border.control)
                )
                .autocorrectionDisabled()
                .disabled(model.submitted)
                .environment(\.locale, Locale(identifier: "it_IT"))
                .accessibilityLabel(Text("Your text"))
                .accessibilityIdentifier("writing.text")
            HStack {
                if !model.submitted { AccentKeys { model.text += $0 } }
                Spacer()
                Text(countLine).dsFont(Tokens.TypeScale.uiCaption)
                    .foregroundStyle(model.wordCountOK ? Color.ds.secondary : Color.ds.warningText)
                    .accessibilityIdentifier("writing.count")
            }
        }
    }

    private var countLine: String {
        guard let w = model.writing.words else { return "\(model.wordCount) words" }
        return "\(model.wordCount) words · \(w.min)–\(w.max)"
    }

    @ViewBuilder private var feedback: some View {
        if !model.isForm {
            VStack(alignment: .leading, spacing: Tokens.Space.m) {
                ForEach(model.writing.points ?? [], id: \.id) { point in
                    let found = model.result?.found.contains(point.id) == true
                    HStack(spacing: Tokens.Space.m) {
                        Image(systemName: found ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(found ? Color.ds.success : Color.ds.inputBorder)
                            .accessibilityHidden(true)
                        Text(point.en).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityValue(Text(found ? "found" : "not found"))
                    .accessibilityIdentifier("writing.point.\(point.id)")
                }
                ForEach(model.suggestions, id: \.tokenIndex) { s in
                    MixedText(text: "*\(s.token)*: did you mean *\(s.suggestion)*?", style: Tokens.TypeScale.uiCallout)
                }
                if let m = model.writing.model {
                    Card {
                        VStack(alignment: .leading, spacing: Tokens.Space.s) {
                            Text("A model answer").dsFont(Tokens.TypeScale.uiCaption)
                                .foregroundStyle(Color.ds.secondary)
                            ItalianText(m.text)
                        }
                    }
                }
            }
        }
    }
}

// MARK: - Relay to a friend

struct RelayView: View {
    @Bindable var model: RelayModel
    let audio: ExerciseAudio
    /// The Italian the learner reads (a text or a real-world layout), resolved by the player; nil for heard sources.
    var source: SourceText?
    let onContinue: () -> Void
    @FocusState private var fieldFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
            ExerciseInstruction("Help a friend")
            if let source {
                SourcePanel(source: source).accessibilityIdentifier("relay.source")
            }
            if let heard = audio.audioID(forText: model.relay.audioTextId) {
                HStack {
                    Spacer()
                    BigPlayButton(
                        isPlaying: audio.isPlaying(heard), action: { audio.toggle(heard) },
                        identifier: "relay.play")
                    Spacer()
                }
            }
            HStack(alignment: .top, spacing: Tokens.Space.m) {
                Image(systemName: "bubble.left.fill").foregroundStyle(Color.ds.secondary).accessibilityHidden(true)
                Text(model.relay.friendEn).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("relay.friend")
            TextField("Reply in English", text: $model.response)
                .dsFont(Tokens.TypeScale.uiBody)
                .textFieldStyle(.roundedBorder)
                .focused($fieldFocused)
                .onSubmit { model.check() }
                .disabled(presentation != nil || model.isDone)
                .accessibilityIdentifier("answer.field")
            if let p = presentation {
                PresentedFeedback(
                    presentation: p,
                    onTryAgain: {
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
            state: model.machine.state, context: model.machine.context, answer: model.answerText,
            rule: nil, canShowAnswer: false)
    }
}
