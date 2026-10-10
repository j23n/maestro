#if FEEDBACK
    import FeedbackKit
#endif
import LearningCore
import SwiftUI

/// The tab shell (docs/07 § Navigation): Today, Course, Words and Settings in a sidebar-adaptable `TabView`. A step
/// opens the lesson player over everything (full screen on iPhone and iPad, the whole window on Mac).
struct MainTabs: View {
    let deps: AppDependencies
    /// Bound so the Mac comes back to the tab a player was opened from: there the tabs leave the window while it plays.
    @State private var tab: MainTab = .today
    @State private var playing: PlayRequest?
    @State private var coursePath: [UnitID] = []
    @State private var reviewing: ReviewRequest?
    @State private var takingFinal: FinalCheckRequest?

    var body: some View {
        TabView(selection: $tab) {
            Tab("Today", systemImage: "sun.max", value: MainTab.today) {
                NavigationStack { today }
            }
            Tab("Course", systemImage: "book", value: MainTab.course) {
                NavigationStack(path: $coursePath) {
                    // Review mode opens every unit and adds Jump to and Review comments (M6.10).
                    CourseView(
                        rows: deps.review?.unlocked(deps.app.courseRows) ?? deps.app.courseRows,
                        footer: deps.app.courseFooter
                    ) { coursePath.append($0) }
                    .modifier(
                        ReviewCourseTools(review: deps.review) { playing = PlayRequest(step: $0.step, jump: $0) }
                    )
                    .navigationDestination(for: UnitID.self) { unit in
                        if let o = deps.app.overview(unit: unit) {
                            UnitView(overview: o) {
                                playing = PlayRequest(step: $0)
                            } accessory: {
                                FinalCheckCard(deps: deps, unit: unit) { takingFinal = FinalCheckRequest() }
                            }
                        }
                    }
                }
            }
            Tab("Words", systemImage: "list.bullet", value: MainTab.words) {
                NavigationStack { WordsScreen(app: deps.app) }
            }
            // Every platform has the Settings tab; the Mac also has the ⌘, Settings window (docs/07 § Screen map).
            Tab("Settings", systemImage: "gearshape", value: MainTab.settings) {
                NavigationStack {
                    SettingsScreen(
                        app: deps.app, sync: deps.syncSettings, studyBuild: deps.config.studyBuild,
                        services: deps.services)
                }
            }
        }
        .tabViewStyle(.sidebarAdaptable)
        .playerPresentation(item: $playing) { request in
            PlayerHost(deps: deps, step: request.step, jump: request.jump) { playing = nil }
        }
        .playerPresentation(item: $takingFinal) { _ in
            FinalCheckHost(deps: deps) { takingFinal = nil }
        }
        .playerPresentation(item: $reviewing) { _ in
            ReviewHost(
                deps: deps, onDismiss: { reviewing = nil },
                onNextStory: {
                    reviewing = nil
                    if let step = deps.app.today?.continueCard?.stepID { playing = PlayRequest(step: step) }
                })
        }
        // After the presentations, so a player taking the Mac window doesn't run these again when the tabs return.
        .onAppear { deps.audioPlayer.onStop = { [app = deps.app] report in app.audioPlayed(report) } }
        .task { await deps.review?.attach(to: deps.app) }
        #if FEEDBACK
            // Where the app is, for a feedback report (ADR-23): the tab, and the step or session being played.
            .onChange(of: feedbackScreen, initial: true) { _, screen in deps.feedback.currentScreen = { screen } }
            .onDisappear { deps.feedback.currentScreen = { nil } }
        #endif
    }

    #if FEEDBACK
        private var feedbackScreen: String {
            var parts = ["tab \(tab)"]
            if let playing { parts.append("playing step \(playing.step)") }
            if reviewing != nil { parts.append("review session") }
            if takingFinal != nil { parts.append("final check") }
            return parts.joined(separator: ", ")
        }
    #endif

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
    /// Review mode's jump menu: open exactly at this step's first page or exercise. Nil for every other open (Today's
    /// Continue, the Unit overview), where a half-done step resumes (`ReviewMode.prepare`).
    var jump: ReviewJump? = nil
    var id: StepID { step }
}

/// The tabs of the shell (docs/07 § Navigation).
enum MainTab: Hashable {
    case today, course, words, settings
}

extension View {
    /// The player covers the app (docs/02 § App): `fullScreenCover` on iPhone and iPad; on Mac, which has no
    /// full-screen cover, the window's content switches to the player until it closes.
    @ViewBuilder
    func playerPresentation<Item: Identifiable, Content: View>(
        item: Binding<Item?>, @ViewBuilder content: @escaping (Item) -> Content
    ) -> some View {
        #if os(macOS)
            modifier(WindowPlayer(item: item, player: content))
        #else
            fullScreenCover(item: item, content: content)
        #endif
    }
}

#if os(macOS)
    /// The Mac's player presentation: the player instead of the tabs, not over them, so the window's toolbar,
    /// sidebar and keyboard shortcuts are the player's alone. The tabs are rebuilt when it closes; their selection and
    /// the Course path are MainTabs' state, so the learner is back where the player was opened.
    private struct WindowPlayer<Item: Identifiable, Player: View>: ViewModifier {
        @Binding var item: Item?
        let player: (Item) -> Player

        func body(content: Content) -> some View {
            ZStack {
                if let item {
                    // A new item is a new player, as with `fullScreenCover(item:)`.
                    player(item).id(item.id)
                } else {
                    content
                }
            }
        }
    }
#endif

/// Loads a step and runs the lesson player with the real audio and speech adapters; writes the session event and
/// shows the mini-preview ("Before we go on") when a step needs words the learner hasn't met.
struct PlayerHost: View {
    let deps: AppDependencies
    let step: StepID
    /// Review mode's jump menu only (`PlayRequest.jump`).
    var jump: ReviewJump? = nil
    let onDismiss: () -> Void
    @State private var launch: AppModel.PlayerLaunch?
    @State private var services: PlayerServices?
    @State private var miniPreview: MiniPreviewRequest?
    @State private var failed = false
    @State private var openedAt = Date()
    @State private var checkResult: CheckResultContent?
    /// The step playing now: `step`, then the unit's first lesson after its opener.
    @State private var current: StepID?
    /// The opener of a unit with nothing written past it (a dev pack).
    @State private var unwrittenUnit: Int?

    var body: some View {
        Group {
            if let checkResult {
                CheckResultView(content: checkResult, onDone: finish, onRetake: retake)
            } else if let unwrittenUnit {
                UnwrittenUnitPage(unitNumber: unwrittenUnit, onDone: onDismiss)
            } else if let launch, let services {
                LessonPlayerView(
                    model: launch.model, services: services, env: launch.environment, sink: launch.sink,
                    onStepChange: { change in
                        let missing = deps.app.stepChanged(change, sessionID: launch.sessionID)
                        // Review mode (dev pack, Review and Debug builds only) shows content as authored, without
                        // the eligibility mini-preview (docs/13 § Review mode); learners always get it.
                        if !missing.isEmpty, let started = change.started, review == nil {
                            miniPreview = MiniPreviewRequest(step: started, pairs: missing)
                        }
                    },
                    onClose: finish,
                    // Review mode pages through a check without scoring it (`scoresCheck`).
                    onFinish: {
                        if AppModel.isOpenerOnly(launch.model.bundle) {
                            continueAfterOpener(launch)
                        } else if launch.scoresCheck(review: review) {
                            showCheckResult()
                        } else {
                            finish()
                        }
                    },
                    review: review, debug: deps.services.debug)
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

    /// Review mode when it is on (a dev pack in a Review or Debug build); nil for learners.
    private var review: ReviewMode? { deps.review?.isActive == true ? deps.review : nil }

    private func load(fresh: Bool = false) async {
        let step = current ?? self.step
        do {
            guard let l = try await deps.app.launch(step: step, fresh: fresh) else {
                failed = true
                return
            }
            // The answer tap on every open; an exact move only for a pick from the jump menu (a half-done step resumes).
            let picked = current == nil ? jump : nil  // the jump menu's pick applies to the first step only
            review?.prepare(l, at: picked ?? ReviewJump(step: step), exact: picked != nil)
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

    /// The opener's button goes on into the unit (docs/06 § Opener): its session ends and the unit's next step opens
    /// in the same player; a unit with nothing past its opener says so instead of "Bravo".
    private func continueAfterOpener(_ opener: AppModel.PlayerLaunch) {
        deps.app.endSession(opener, activeSeconds: Int(Date().timeIntervalSince(openedAt)))
        let unit = opener.model.bundle.unitID
        Task {
            await deps.app.settle()
            guard let next = deps.app.stepAfterOpener(of: unit) else {
                unwrittenUnit = deps.app.outline.unit(unit)?.number ?? 0
                return
            }
            launch = nil
            services = nil
            current = next
            openedAt = Date()
            await load()
        }
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
                    onNextStory: deps.app.today?.continueCard == nil ? nil : { finishThen(onNextStory) },
                    debug: deps.services.debug)
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
