import LearningCore
import SwiftUI

/// The tab shell (docs/07 § Navigation): Today, Course, Words and Settings in a sidebar-adaptable `TabView`. A step
/// opens the lesson player over everything (full screen on iPhone and iPad, a sheet-sized window on Mac).
struct MainTabs: View {
    let deps: AppDependencies
    @State private var playing: PlayRequest?
    @State private var coursePath: [UnitID] = []
    @State private var reviewing: ReviewRequest?

    var body: some View {
        TabView {
            Tab("Today", systemImage: "sun.max") {
                NavigationStack { today }
            }
            Tab("Course", systemImage: "book") {
                NavigationStack(path: $coursePath) {
                    CourseView(rows: deps.app.courseRows, footer: deps.app.courseFooter) { coursePath.append($0) }
                        .navigationDestination(for: UnitID.self) { unit in
                            if let o = deps.app.overview(unit: unit) {
                                UnitView(overview: o) { playing = PlayRequest(step: $0) }
                            }
                        }
                }
            }
            Tab("Words", systemImage: "list.bullet") {
                NavigationStack { WordsScreen(app: deps.app) }
            }
            #if !os(macOS)
                Tab("Settings", systemImage: "gearshape") {
                    NavigationStack {
                        SettingsScreen(
                            app: deps.app, sync: deps.syncSettings, studyBuild: deps.config.studyBuild,
                            services: deps.services)
                    }
                }
            #endif
        }
        .tabViewStyle(.sidebarAdaptable)
        .onAppear { deps.audioPlayer.onStop = { [app = deps.app] report in app.audioPlayed(report) } }
        .playerPresentation(item: $playing) { request in
            PlayerHost(deps: deps, step: request.step) { playing = nil }
        }
        .playerPresentation(item: $reviewing) { _ in
            ReviewHost(
                deps: deps, onDismiss: { reviewing = nil },
                onNextStory: {
                    reviewing = nil
                    if let step = deps.app.today?.continueCard?.stepID { playing = PlayRequest(step: step) }
                })
        }
    }

    @ViewBuilder private var today: some View {
        if let content = deps.app.today {
            TodayView(
                content: content, onStartReview: { reviewing = ReviewRequest() },
                onContinue: { playing = PlayRequest(step: $0.stepID) })
        } else {
            ProgressView()
        }
    }
}

struct PlayRequest: Identifiable, Hashable {
    let step: StepID
    var id: StepID { step }
}

extension View {
    /// The player covers the app: `fullScreenCover` on iPhone and iPad, a large sheet on Mac.
    @ViewBuilder
    func playerPresentation<Item: Identifiable, Content: View>(
        item: Binding<Item?>, @ViewBuilder content: @escaping (Item) -> Content
    ) -> some View {
        #if os(macOS)
            sheet(item: item) {
                content($0).frame(
                    minWidth: Tokens.Size.macMinWindowWidth,
                    minHeight: Tokens.Size.macMinWindowHeight)
            }
        #else
            fullScreenCover(item: item, content: content)
        #endif
    }
}

/// Loads a step and runs the lesson player with the real audio and speech adapters; writes the session event and
/// shows the mini-preview ("Before we go on") when a step needs words the learner hasn't met.
struct PlayerHost: View {
    let deps: AppDependencies
    let step: StepID
    let onDismiss: () -> Void
    @State private var launch: AppModel.PlayerLaunch?
    @State private var services: PlayerServices?
    @State private var miniPreview: MiniPreviewRequest?
    @State private var failed = false
    @State private var openedAt = Date()
    @State private var checkResult: CheckResultContent?

    var body: some View {
        Group {
            if let checkResult {
                CheckResultView(content: checkResult, onDone: finish, onRetake: retake)
            } else if let launch, let services {
                LessonPlayerView(
                    model: launch.model, services: services, env: launch.environment, sink: launch.sink,
                    onStepChange: { change in
                        let missing = deps.app.stepChanged(change, sessionID: launch.sessionID)
                        if !missing.isEmpty, let started = change.started {
                            miniPreview = MiniPreviewRequest(step: started, pairs: missing)
                        }
                    },
                    onClose: finish, onFinish: { launch.kind == .check ? showCheckResult() : finish() })
            } else if failed {
                MissingContentPage(onContinue: onDismiss)
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task { await load() }
        .debugOverlay(
            deps.services.debug, step: launch?.model.currentStep?.id, exercise: launch?.model.currentExercise?.id
        )
        .sheet(item: $miniPreview) { request in
            MiniPreviewSheet(words: deps.app.words(for: request.pairs), services: services) {
                deps.app.introduceMissing(request.pairs, step: request.step)
                miniPreview = nil
            }
            .interactiveDismissDisabled()
        }
    }

    private func load(fresh: Bool = false) async {
        do {
            guard let l = try await deps.app.launch(step: step, fresh: fresh) else {
                failed = true
                return
            }
            let resolver: any AudioResolving = deps.app.audioCatalog ?? StaticAudioResolver()
            services = PlayerServices(
                audio: ExerciseAudio(player: deps.audioPlayer, resolver: resolver),
                speech: SpeechCapture(recognizer: deps.speech),
                onGloss: { [app = deps.app] text, line, token, item in
                    app.glossTapped(text: text, line: line, token: token, item: item)
                })
            launch = l
        } catch {
            failed = true
        }
    }

    private func showCheckResult() {
        guard let launch, let result = deps.app.completeCheck(launch) else { return finish() }
        checkResult = result
    }

    /// A retake is a fresh sitting of the check (a new session; every answer is scored again).
    private func retake() {
        if let launch { deps.app.endSession(launch, activeSeconds: Int(Date().timeIntervalSince(openedAt))) }
        checkResult = nil
        launch = nil
        openedAt = Date()
        Task { await load(fresh: true) }
    }

    private func finish() {
        if let launch { deps.app.endSession(launch, activeSeconds: Int(Date().timeIntervalSince(openedAt))) }
        onDismiss()
    }
}

struct MiniPreviewRequest: Identifiable {
    let step: StepID
    let pairs: [ItemSkillPair]
    var id: StepID { step }
}

/// "Before we go on" (docs/06 § Shared player behaviour): a meet card per missing word, then Continue, which
/// records them as introduced `via: catchup`.
struct MiniPreviewSheet: View {
    let words: [WordInfo]
    let services: PlayerServices?
    let onContinue: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
            Text("Before we go on").dsFont(Tokens.TypeScale.screenTitle).foregroundStyle(Color.ds.ink)
                .accessibilityAddTraits(.isHeader)
            Text("This part uses a few words you haven't met yet.")
                .dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
            ScrollView {
                VStack(spacing: Tokens.Space.m) {
                    ForEach(Array(words.enumerated()), id: \.element.itemID) { n, w in
                        Button {
                            services?.audio.play(w.audioID, context: .item)
                        } label: {
                            Card {
                                VStack(alignment: .leading, spacing: Tokens.Space.xs) {
                                    ItalianText(w.display, style: Tokens.TypeScale.rowTitle)
                                    Text("\(w.partOfSpeech) · \(w.gloss)").dsFont(Tokens.TypeScale.uiCallout)
                                        .foregroundStyle(Color.ds.secondary)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("minipreview.card.\(n)")
                    }
                }
            }
            Button("Continue", action: onContinue)
                .buttonStyle(.dsPrimary)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("minipreview.continue")
        }
        .padding(Tokens.Space.xxl)
        .background(Color.ds.background)
    }
}

struct ReviewRequest: Identifiable {
    let id = UUID()
}

/// Builds today's review session and plays it; writes the `session` event when it closes or completes.
struct ReviewHost: View {
    let deps: AppDependencies
    let onDismiss: () -> Void
    let onNextStory: () -> Void
    @State private var launch: AppModel.ReviewLaunch?
    @State private var services: PlayerServices?
    @State private var nothingToDo = false
    @State private var openedAt = Date()

    var body: some View {
        Group {
            if let launch, let services {
                ReviewSessionView(
                    model: launch.model, services: services,
                    complete: {
                        CompleteContent(
                            summary: launch.model.summary, words: deps.app.words, nextReview: deps.app.nextReview,
                            week: deps.app.week
                                ?? WeekProgress(
                                    weekStart: 0, days: Array(repeating: false, count: 7),
                                    goal: deps.app.settings.goalDaysPerWeek))
                    },
                    onClose: finish, onDone: finish,
                    onNextStory: deps.app.today?.continueCard == nil ? nil : { finishThen(onNextStory) })
            } else if nothingToDo {
                LessonDonePage(title: "today's review", onDone: onDismiss)
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task {
            do {
                guard let l = try await deps.app.startReview() else {
                    nothingToDo = true
                    return
                }
                let resolver: any AudioResolving = deps.app.audioCatalog ?? StaticAudioResolver()
                services = PlayerServices(
                    audio: ExerciseAudio(player: deps.audioPlayer, resolver: resolver),
                    speech: SpeechCapture(recognizer: deps.speech))
                launch = l
            } catch {
                nothingToDo = true
            }
        }
        .debugOverlay(deps.services.debug, step: nil, exercise: launch?.model.payload?.id)
    }

    private func finish() { finishThen(onDismiss) }

    private func finishThen(_ next: () -> Void) {
        if let launch {
            deps.app.endSession(
                sessionID: launch.sessionID, kind: .review, startedAt: launch.startedAt,
                activeSeconds: Int(Date().timeIntervalSince(openedAt)))
        }
        next()
    }
}
