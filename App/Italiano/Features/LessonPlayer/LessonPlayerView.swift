import LearningCore
import SwiftUI

/// The lesson player (docs/06 § Shared player behaviour): close (X, Esc), progress bar with `n / total`, the step
/// title, then the current page: a content page (StepPages) or an exercise (ExerciseHostView). Closing saves nothing
/// extra; the resume cursor is derived from attempts.
struct LessonPlayerView: View {
    let model: LessonPlayerModel
    let services: PlayerServices
    let env: ExerciseEnvironment
    let sink: EventAttemptSink
    /// Writes `stepCompleted` / `stepStarted`.
    var onStepChange: (LessonPlayerModel.StepChange) -> Void = { _ in }
    let onClose: () -> Void
    let onFinish: () -> Void
    /// Review mode's tools (bar, comments, answer key); nil for learners.
    var review: ReviewMode? = nil
    @State private var host: ExerciseHostModel?
    @State private var hostPosition: Int?

    var body: some View {
        VStack(spacing: 0) {
            chrome
            Divider()
            page
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .id(model.position)
        }
        .background(Color.ds.background)
        .modifier(
            ReviewPlayerTools(
                review: review, model: model, host: hostPosition == model.position ? host : nil,
                move: { move(to: $0) })
        )
        .onAppear {
            sink.stepID = model.currentStep?.id
            if let step = model.openingStep { onStepChange(.init(completed: nil, started: step)) }
        }
        .onChange(of: model.position, initial: true) { _, _ in makeHost() }
    }

    private var chrome: some View {
        VStack(spacing: Tokens.Space.s) {
            HStack(spacing: Tokens.Space.l) {
                Button {
                    services.audio.stop()
                    onClose()
                } label: {
                    Image(systemName: "xmark").font(.system(size: 20, weight: .medium))
                        .foregroundStyle(Color.ds.ink)
                        .frame(width: Tokens.Size.minTouch, height: Tokens.Size.minTouch)
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.cancelAction)
                .lessonMenu(.closeLesson) {
                    services.audio.stop()
                    onClose()
                }
                .accessibilityLabel(Text("Close"))
                .accessibilityIdentifier("player.close")
                if model.exerciseTotal > 0 {
                    DSProgressBar(value: model.progress)
                        .accessibilityIdentifier("player.progress")
                    Text("\(model.exerciseNumber) / \(model.exerciseTotal)")
                        .dsFont(Tokens.TypeScale.uiCallout)
                        .foregroundStyle(Color.ds.secondary)
                        .monospacedDigit()
                } else {
                    Spacer()
                }
            }
            if let title = model.currentStep?.title {
                Text(title).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
            }
        }
        .padding(.horizontal, Tokens.Space.l)
        .padding(.vertical, Tokens.Space.s)
    }

    @ViewBuilder private var page: some View {
        if model.isFinished {
            LessonDonePage(title: model.bundle.title, onDone: onFinish)
        } else if let entry = model.current {
            switch entry.page {
            case .opener:
                OpenerPage(bundle: model.bundle, onContinue: advance)
            case .meet(let ids):
                MeetPage(words: ids.compactMap { model.bundle.items[$0] }, services: services, onContinue: advance)
            case .story(let id):
                textPage(id) { StoryPage(text: $0, bundle: model.bundle, services: services, onContinue: advance) }
            case .listening(let id, let plays):
                textPage(id) { ListeningPage(text: $0, plays: plays, services: services, onContinue: advance) }
            case .transcript(let id):
                textPage(id) {
                    TranscriptPage(text: $0, bundle: model.bundle, services: services, onContinue: advance)
                }
            case .reading(let id):
                textPage(id) { ReadingPage(text: $0, services: services, onContinue: advance) }
            case .note(let id):
                if let note = model.bundle.notes[id] {
                    NotePage(note: note, onContinue: advance)
                } else {
                    MissingContentPage(onContinue: advance)
                }
            case .fluency(let ids, let rate):
                FluencyPage(
                    texts: ids.compactMap { model.bundle.texts[$0] }, rate: rate, services: services,
                    onDone: advance)
            case .checkSection(_, let title):
                CheckSectionPage(title: title, onContinue: advance)
            case .exercise:
                if let host, hostPosition == model.position, let payload = model.currentExercise {
                    ExerciseHostView(
                        host: host, payload: payload, bundle: model.bundle, services: services,
                        onContinue: advance)
                } else {
                    MissingContentPage(onContinue: advance)
                }
            }
        }
    }

    @ViewBuilder private func textPage<V: View>(_ id: TextID, @ViewBuilder _ make: (PlayerText) -> V) -> some View {
        if let text = model.bundle.texts[id] { make(text) } else { MissingContentPage(onContinue: advance) }
    }

    private func makeHost() {
        guard let payload = model.currentExercise else {
            host = nil
            hostPosition = nil
            return
        }
        host = ExerciseHostModel.make(payload, env: env, sink: sink)
        hostPosition = model.position
    }

    private func advance() {
        services.audio.stop()
        services.speech.reset()
        let change = model.advance()
        sink.stepID = model.currentStep?.id
        if change != .init() { onStepChange(change) }
    }

    /// Review mode's Previous and Next: any page, answered or not.
    private func move(to index: Int) {
        services.audio.stop()
        services.speech.reset()
        let change = model.move(to: index)
        sink.stepID = model.currentStep?.id
        if change != .init() { onStepChange(change) }
    }
}

/// Draws the exercise view for a host model.
struct ExerciseHostView: View {
    let host: ExerciseHostModel
    let payload: ExercisePayload
    let bundle: LessonBundle
    let services: PlayerServices
    let onContinue: () -> Void

    var body: some View {
        ScrollView {
            content.padding(.vertical, Tokens.Space.xxl)
        }
        .scrollDismissesKeyboard(.interactively)
    }

    @ViewBuilder private var content: some View {
        switch host {
        case .typed(let m):
            // The view shows "Say it" only when the model allows it (speech on, recall, not an assessment).
            TypedExerciseView(model: m, payload: payload, onSayIt: { sayIt(m) }, onContinue: onContinue)
        case .choice(let m):
            ChoiceExerciseView(
                model: m, audio: services.audio, source: bundle.source(for: payload),
                onContinue: onContinue)
        case .match(let m):
            MatchExerciseView(model: m, audio: services.audio, onContinue: onContinue)
        case .building(let m):
            SentenceBuildingView(model: m, audio: services.audio, onContinue: onContinue)
        case .dictation(let m):
            DictationView(model: m, audio: services.audio, onContinue: onContinue)
        case .repeatAfterMe(let m):
            RepeatView(model: m, audio: services.audio, speech: services.speech, onContinue: onContinue)
        case .conversation(let m):
            ConversationView(
                model: m, audio: services.audio, speech: services.speech,
                characterName: bundle.characters[m.conversation.with] ?? "", onContinue: onContinue)
        case .talk(let m):
            TalkView(model: m, audio: services.audio, speech: services.speech, onContinue: onContinue)
        case .writing(let m):
            WritingView(model: m, onContinue: onContinue)
        case .relay(let m):
            RelayView(model: m, audio: services.audio, source: bundle.source(for: payload), onContinue: onContinue)
        }
    }

    private func sayIt(_ m: TypedExerciseModel) {
        Task {
            if let r = await services.speech.capture(expected: [m.modelAnswer]) { m.submitSpoken(r) }
        }
    }
}

/// The end of a lesson: a short celebration and Done (the next step is chosen on Today).
struct LessonDonePage: View {
    let title: String
    let onDone: () -> Void

    var body: some View {
        VStack(spacing: Tokens.Space.xxl) {
            Spacer()
            Mascot(pose: .cheer, size: 150, decorative: true)
            ItalianText("Bravo!", style: Tokens.TypeScale.celebration)
            Text("You finished \(title).").dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
            Spacer()
            Button("Done", action: onDone)
                .buttonStyle(.dsPrimary)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("complete.done")
        }
        .readableColumn()
    }
}

/// A page whose content the pack doesn't have (a stale or partial pack): say so and let the learner go on.
struct MissingContentPage: View {
    let onContinue: () -> Void

    var body: some View {
        VStack(spacing: Tokens.Space.xxl) {
            Spacer()
            Mascot(pose: .think, size: 96, decorative: true)
            Text("This part isn't available in this version of the course.")
                .dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
                .multilineTextAlignment(.center)
            Spacer()
            ContinueButton(action: onContinue)
        }
        .readableColumn()
        .accessibilityIdentifier("player.missing")
    }
}
