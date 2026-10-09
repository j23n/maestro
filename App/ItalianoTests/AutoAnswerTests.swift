import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// M6.3: the Debug menu's auto-answer (`AutoAnswer`) through the real exercise models, graders and engine, and the
/// launch arguments UI tests use with it (`-ITAAutoAnswer`, `-ITAFreshLearner`, `-ITALearner`).
@MainActor
@Suite struct AutoAnswerTests {
    let shell = ShellTestApp()

    /// A learner whose answers must fit them: feminine forms with strict forms on, a name, and a country from the
    /// pack (personal slots are filled from it).
    func personalApp() async -> AppModel {
        let app = await shell.started()
        app.set(.profileForms, to: .string("f"))
        app.set(.answersStrictForms, to: .bool(true))
        app.set(.profileName, to: .string("Anna"))
        app.set(.profileCountry, to: .string("us"))
        await app.settle()
        return app
    }

    func environment(
        _ app: AppModel, _ context: AttemptContext, profile: LearnerProfile, canSpeak: Bool
    )
        -> ExerciseEnvironment
    {
        ExerciseEnvironment(
            context: context, profile: profile, knownForms: app.knownForms, letterNames: app.letterNames, nowMs: { 0 },
            canSpeak: canSpeak)
    }

    // MARK: - Every format

    @Test(arguments: [AttemptContext.lesson, .review, .check, .placement, .final])
    func everyExampleExerciseIsAnsweredCorrectly(context: AttemptContext) async throws {
        let app = await personalApp()
        #expect(app.profile.forms == .f && app.profile.country != nil)
        for profile in [LearnerProfile.unspecified, app.profile] {
            for canSpeak in [false, true] {
                for (id, payload) in try PayloadFixtures.exercises().sorted(by: { $0.key < $1.key }) {
                    let label = "\(id) in \(context), speech \(canSpeak), forms \(profile.forms)"
                    let sink = RecordingAttemptSink()
                    let env = environment(app, context, profile: profile, canSpeak: canSpeak)
                    let host = try #require(ExerciseHostModel.make(payload, env: env, sink: sink), "\(label)")
                    #expect(AutoAnswer.answer(host, .correct), "\(label)")
                    #expect(host.isDone, "\(label)")
                    // Listen-and-repeat without speech recognition is ungraded: nothing is recorded (docs/06 §11).
                    let ungraded = payload.format == .repeat && !canSpeak
                    #expect(sink.drafts.isEmpty == ungraded, "\(label)")
                    for d in sink.drafts {
                        #expect(d.outcome == .correct, "\(label): \(d.outcome) for \(d.response ?? "-")")
                        #expect(d.targets.allSatisfy { $0.outcome == .correct }, "\(label)")
                    }
                    #expect(!AutoAnswer.answer(host, .correct), "\(label): nothing is left to answer")
                }
            }
        }
    }

    @Test func aWrongAnswerThenTheRightOne() async throws {
        let app = await personalApp()
        for (id, payload) in try PayloadFixtures.exercises().sorted(by: { $0.key < $1.key }) {
            let sink = RecordingAttemptSink()
            let env = environment(app, .lesson, profile: app.profile, canSpeak: true)
            let host = try #require(ExerciseHostModel.make(payload, env: env, sink: sink))
            #expect(AutoAnswer.answer(host, .wrong), "\(id)")
            if payload.format == .match {
                // A match records once, when every pair is matched; the wrong pairing stays that pair's outcome.
                #expect(sink.drafts.isEmpty && !host.isDone, "\(id)")
            } else {
                #expect(sink.drafts.map(\.outcome) == [.wrong], "\(id): \(sink.drafts.map(\.outcome))")
            }
            #expect(AutoAnswer.answer(host, .correct), "\(id)")
            #expect(host.isDone, "\(id)")
            let last = try #require(sink.drafts.last, "\(id)")
            if payload.format == .match {
                #expect(last.outcome == .wrong && last.targets.filter { $0.outcome == .wrong }.count == 1, "\(id)")
            } else {
                #expect(last.outcome == .correct, "\(id): \(last.outcome)")
            }
        }
    }

    @Test func twoWrongAnswersShowTheAnswerAndContinueAcknowledgesIt() async throws {
        let app = await personalApp()
        let sink = RecordingAttemptSink()
        let env = environment(app, .lesson, profile: app.profile, canSpeak: false)
        let host = try #require(
            ExerciseHostModel.make(try PayloadFixtures.exercise("u02.l1.ex01"), env: env, sink: sink))
        guard case .typed(let m) = host else {
            Issue.record("expected a typed exercise")
            return
        }
        AutoAnswer.answer(host, .wrong)
        AutoAnswer.answer(host, .wrong)
        #expect(m.machine.state == .answerShown(.missedTwice) && !host.isDone)
        #expect(sink.drafts.map(\.attemptIndex) == [1, 2] && sink.drafts.allSatisfy { $0.outcome == .wrong })
        var advanced = 0
        AutoAnswer.answerAndContinue(host) { advanced += 1 }
        #expect(host.isDone && advanced == 1 && sink.drafts.count == 2)  // acknowledging records nothing
        #expect(!AutoAnswer.answer(host, .wrong))
    }

    @Test func aTypedAnswerInACheckMovesOnByItself() async throws {
        let app = await personalApp()
        let sink = RecordingAttemptSink()
        let env = environment(app, .check, profile: app.profile, canSpeak: false)
        let typed = try #require(
            ExerciseHostModel.make(try PayloadFixtures.exercise("u02.l1.ex04"), env: env, sink: sink))
        var advanced = 0
        AutoAnswer.answerOnPage(typed, .correct) { advanced += 1 }
        #expect(typed.isDone && typed.movesOnWithoutFeedback && advanced == 1)
        // A choice shows its own Continue: the bar's answer leaves the page to it.
        let choice = try #require(
            ExerciseHostModel.make(try PayloadFixtures.exercise("u02.check.01"), env: env, sink: sink))
        AutoAnswer.answerOnPage(choice, .correct) { advanced += 1 }
        #expect(choice.isDone && !choice.movesOnWithoutFeedback && advanced == 1)
        // Content pages have no exercise: "Answer and continue" only moves on.
        AutoAnswer.answerAndContinue(nil) { advanced += 1 }
        #expect(advanced == 2)
    }

    @Test func patternAnswersFitTheLearner() throws {
        let pattern = try AnswerPattern("Sono {m:nato|f:nata} {ME.home}.")
        let unspecified = AutoAnswer.candidateTexts(pattern, profile: .unspecified)
        #expect(unspecified.first == "Sono nato Alex.")
        let her = LearnerProfile(
            forms: .f, strictForms: true, name: "Anna",
            country: .init(id: "xx", nameIt: "X", homePhrase: "in X", nationalityM: "xm", nationalityF: "xf"))
        #expect(AutoAnswer.candidateTexts(pattern, profile: her) == ["Sono nata in X.", "Sono nata in X."])
        #expect(AutoAnswer.fillSlots("Mi chiamo {NAME}, ho {NUMBER} anni", profile: her) == "Mi chiamo Anna, ho 3 anni")
        // The grader decides: the first `correct` wins over an earlier `almost`.
        let picked = AutoAnswer.correctText(patterns: [pattern], profile: .unspecified) {
            $0.contains("nata") ? .correct : .almost
        }
        #expect(picked == "Sono nata Alex.")
        #expect(AutoAnswer.correctText(patterns: [pattern], profile: .unspecified) { _ in .wrong } == nil)
    }

    // MARK: - Through the engine

    /// Plays one step's lesson (or unit-level step) from its first page with "Answer and continue", as a UI test
    /// tapping `debug.autoAdvance` does, writing the step events the player writes. `allowMiniPreview`: a step may
    /// need words the pack teaches in a lesson it doesn't have yet (the mini pack has only Lesson 1 of Unit 2); they
    /// are introduced as the mini-preview's Continue does. Otherwise no step may need it (hard rule 4).
    func autoPlay(
        _ app: AppModel, step: StepID, allowMiniPreview: Bool = false
    ) async throws -> (
        AppModel.PlayerLaunch, [AttemptDraft]
    ) {
        let launch = try #require(try await app.launch(step: step))
        var drafts: [AttemptDraft] = []
        let previous = launch.sink.onRecord
        launch.sink.onRecord = { d in
            previous?(d)
            drafts.append(d)
        }
        let player = launch.model
        launch.sink.stepID = player.currentStep?.id
        func changed(_ change: LessonPlayerModel.StepChange) {
            let missing = app.stepChanged(change, sessionID: launch.sessionID)
            guard let started = change.started, !missing.isEmpty else { return }
            #expect(allowMiniPreview, "\(started) needs \(missing)")
            app.introduceMissing(missing, step: started)
        }
        if let first = player.openingStep { changed(.init(completed: nil, started: first)) }
        var pages = 0
        while !player.isFinished, pages < 300 {
            let host = player.currentExercise.flatMap {
                ExerciseHostModel.make($0, env: launch.environment, sink: launch.sink)
            }
            var change = LessonPlayerModel.StepChange()
            AutoAnswer.answerAndContinue(host) {
                change = player.advance()
                launch.sink.stepID = player.currentStep?.id
            }
            if let host { #expect(host.isDone, "\(player.entries[safe: player.position - 1]?.page as Any)") }
            if change != .init() {
                // As in the app, where a step change comes seconds after the last write: the step that just ended
                // (its introductions included) is stored before the next one is checked for eligibility.
                await app.settle()
                changed(change)
            }
            pages += 1
        }
        #expect(player.isFinished)
        return (launch, drafts)
    }

    @Test(arguments: [false, true])
    func autoAnsweringUnit2Lesson1FinishesEveryStepCorrectly(canSpeak: Bool) async throws {
        let app = await personalApp()
        try await app.debugJump(to: "u02")
        app.canSpeak = canSpeak
        let (launch, drafts) = try await autoPlay(app, step: "u02.l1.step-preview")
        app.endSession(launch, activeSeconds: 60)
        await app.settle()

        let steps = launch.model.bundle.steps.map(\.id)
        #expect(steps.count == 6 && steps.allSatisfy { $0.rawValue.hasPrefix("u02.l1.") })
        let state = try #require(app.state)
        for step in steps { #expect(state.stepProgress(step)?.completedAt != nil, "\(step)") }
        // Every exercise of the lesson was answered, every answer and every target correct.
        var exercises = Set(
            launch.model.entries.compactMap { e -> ExerciseID? in
                if case .exercise(let id) = e.page { return id }
                return nil
            })
        if !canSpeak { exercises.remove("u02.l1.ex14") }  // repeat after me is listen-and-repeat: ungraded
        #expect(Set(drafts.map(\.exerciseID)) == exercises)
        #expect(drafts.allSatisfy { $0.outcome == .correct && $0.targets.allSatisfy { $0.outcome == .correct } })
        #expect(drafts.contains { $0.mode == .spoken } == canSpeak)
        // The words of the lesson now have memory (FSRS ran on correct answers).
        #expect(state.memory.keys.contains { $0.itemId == "w:cornetto" })
        #expect(app.today?.continueCard?.stepID != "u02.l1.step-preview")
    }

    @Test func autoAnsweringTheWholeOfUnit2PassesItsCheck() async throws {
        let app = await personalApp()
        try await app.debugJump(to: "u02")
        app.canSpeak = true  // the speaking section counts (simulated speech, as in the Simulator)
        let order: [StepID] = [
            "u02.step-opener", "u02.l1.step-preview", "u02.step-conversation-1", "u02.step-talk", "u02.step-relay",
            "u02.step-check", "u02.step-fluency",
        ]
        var all: [AttemptDraft] = []
        for step in order {
            let lessonStep = step.rawValue.hasPrefix("u02.l1.")
            let (launch, drafts) = try await autoPlay(app, step: step, allowMiniPreview: !lessonStep)
            all += drafts
            if launch.kind == .check {
                let result = try #require(app.completeCheck(launch))
                #expect(result.passed && result.overall == "100%", "\(result.overall)")
            }
            app.endSession(launch, activeSeconds: 30)
            await app.settle()
        }
        #expect(!all.isEmpty && all.allSatisfy { $0.outcome == .correct })
        let unit = try #require(app.state?.units["u02"])
        #expect(unit.checkPassed == true && unit.checkScore == 1 && unit.state == .completed)
        #expect(app.overview(unit: "u02")?.primary == "Practise this unit again")
    }

    // MARK: - Launch arguments and the Debug menu

    @Test func launchArgumentsForUITests() {
        #expect(LaunchArguments(["/app", "-ITAAutoAnswer"]).autoAnswer)
        #expect(!LaunchArguments(["/app"]).autoAnswer)
        #expect(LaunchArguments(["-ITAFreshLearner"]).learner == .fresh)
        #expect(LaunchArguments(["-ITALearner", "resume-1"]).learner == .named("resume-1"))
        #expect(LaunchArguments(["-ITAFreshLearner", "-ITALearner", "a_b"]).learner == .named("a_b"))
        #expect(LaunchArguments(["-ITALearner", "../up"]).learner == nil)
        #expect(LaunchArguments(["-ITALearner"]).learner == nil)
        #expect(LaunchArguments(["-ITALearner", String(repeating: "x", count: 65)]).learner == nil)
        let all = LaunchArguments(["-ITAJumpToUnit", "u02", "-ITAAutoAnswer", "-ITALearner", "t1"])
        #expect(all == LaunchArguments(jumpToUnit: "u02", autoAnswer: true, learner: .named("t1")))
    }

    @Test func throwawayLearnerDatabasesOnlyWithTheDebugMenu() throws {
        let tmp = URL(fileURLWithPath: "/tmp/x", isDirectory: true)
        let debug = AppConfig.preview
        let release = AppConfig(info: ["ITA_DEBUG_MENU": "NO"])
        let named = LaunchArguments(["-ITALearner", "resume"])
        #expect(
            named.learnerURL(config: debug, temporaryDirectory: tmp, newName: { "n" })?.path
                == "/tmp/x/ItalianoUITests/resume/learner.sqlite")
        var n = 0
        let fresh = LaunchArguments(["-ITAFreshLearner"])
        let first = fresh.learnerURL(config: debug, temporaryDirectory: tmp) {
            n += 1
            return "\(n)"
        }
        let second = fresh.learnerURL(config: debug, temporaryDirectory: tmp) {
            n += 1
            return "\(n)"
        }
        #expect(first != nil && first != second)
        #expect(named.learnerURL(config: release, temporaryDirectory: tmp, newName: { "n" }) == nil)
        #expect(fresh.learnerURL(config: release, temporaryDirectory: tmp, newName: { "n" }) == nil)
        #expect(LaunchArguments([]).learnerURL(config: debug, temporaryDirectory: tmp, newName: { "n" }) == nil)
    }

    @Test func aFreshLearnerDatabaseStartsAtFirstLaunchAndANamedOneResumes() async throws {
        let tmp = shell.folder
        let args = LaunchArguments(["-ITALearner", "resume"])
        func app(_ seed: String) -> AppModel {
            AppModel(
                env: .init(
                    packURL: PackAdaptersTests.packURL,
                    learnerURL: args.learnerURL(config: .preview, temporaryDirectory: tmp, newName: { "n" }),
                    clock: shell.base, ids: SeededUUIDSource(seed: seed), platform: .iPhone))
        }
        let first = app("a")
        await first.start()
        #expect(first.phase == .ready && !first.isOnboarded)
        try await first.debugJumpAtLaunch(to: "u02")
        let again = app("b")
        await again.start()
        #expect(again.isOnboarded && again.state?.placement?.startUnit == "u02")
    }

    @Test func theAutoAnswerBarIsOffUntilTheLaunchArgumentOrTheSwitch() async throws {
        let app = await shell.started()
        let preferences = MemoryPreferences()
        let debug = DebugMenuModel(app: app, clock: nil, speech: nil, preferences: preferences)
        #expect(!debug.autoAnswerEnabled)
        let services = AppServices(
            config: .preview, app: app, notifications: FakeNotificationScheduler(), telemetry: nil, debug: debug)
        await services.afterLaunch(arguments: ["/app", "-ITAAutoAnswer"])
        #expect(debug.autoAnswerEnabled && !debug.showAutoAnswer)
        // The launch argument isn't kept; the Debug menu's switch is.
        let next = DebugMenuModel(app: app, clock: nil, speech: nil, preferences: preferences)
        #expect(!next.autoAnswerEnabled)
        next.showAutoAnswer = true
        #expect(DebugMenuModel(app: app, clock: nil, speech: nil, preferences: preferences).autoAnswerEnabled)

        // Release and Study builds have no Debug menu, so no bar and no launch argument.
        for info in [["ITA_DEBUG_MENU": "NO"], ["ITA_DEBUG_MENU": "NO", "ITA_STUDY_BUILD": "YES"]] {
            let release = AppServices(
                config: AppConfig(info: info), app: app, notifications: FakeNotificationScheduler(),
                telemetry: nil, debug: DebugMenuModel(app: app, clock: nil, speech: nil, preferences: preferences))
            #expect(release.debug == nil)
        }
    }
}
