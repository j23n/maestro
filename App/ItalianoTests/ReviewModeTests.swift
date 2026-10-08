import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// M6.10: review mode on the mini pack (Unit 2's golden lesson). The acceptance proxy is
/// `filesACommentOnU02L1Ex07AndExportsAReviewFile`: it jumps to `u02.l1.ex07`, files a "This should be accepted"
/// and a comment, and exports review files that match `schemas/review-file.schema.json` and the fixtures
/// `pipeline/tests/fixtures/review-app-*.json`, which `content review-import` imports in the pipeline tests.
@MainActor
@Suite struct ReviewModeTests {
    let folder = FileManager.default.temporaryDirectory
        .appendingPathComponent("italiano-review-\(UUID().uuidString)", isDirectory: true)
    let clock = FixedClock(ms: 1_791_271_800_000, tzOffsetMinutes: 120)  // Tue 6 Oct 2026, 07:30 UTC

    static let reviewInfo: [String: Any] = [
        "ITA_REVIEW_MODE": "YES", "ITA_PACK": "dev", "ITA_REVIEW_URL": "https://review.example.org",
        "ITA_REVIEW_TOKEN": "review-token",
    ]

    func app() async -> AppModel {
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let app = AppModel(
            env: .init(
                packURL: PackAdaptersTests.packURL, learnerURL: folder.appendingPathComponent("learner.sqlite"),
                clock: clock, ids: SeededUUIDSource(seed: "learner"), platform: .iPad))
        await app.start()
        return app
    }

    func review(
        info: [String: Any] = Self.reviewInfo, store: (any ReviewDraftStoring)? = InMemoryReviewDraftStore(),
        server: ReviewServer = ReviewServer()
    ) -> ReviewMode? {
        ReviewMode(
            config: AppConfig(info: info), store: store, transport: server, clock: clock,
            ids: SeededUUIDSource(seed: "review"))
    }

    // MARK: - Who gets review mode

    @Test func onlyReviewAndDebugBuildsHaveReviewMode() throws {
        for (file, expected) in [
            ("Debug.xcconfig", true), ("Review.xcconfig", true), ("Release.xcconfig", false),
            ("Study.xcconfig", false),
        ] {
            let config = AppConfig(info: try Xcconfig.values(file))
            #expect(config.reviewMode == expected, "\(file)")
            #expect((review(info: try Xcconfig.values(file)) != nil) == expected, "\(file)")
        }
        // The Review build: dev pack, no sync, no telemetry, even with a study endpoint and token.
        var info = try Xcconfig.values("Review.xcconfig")
        info["ITA_TELEMETRY_URL"] = "https://study.example.org"
        info["ITA_STUDY_TOKEN"] = "t"
        info["ITA_SYNC_ENABLED"] = "YES"
        let reviewBuild = AppConfig(info: info)
        #expect(reviewBuild.pack == .dev && !reviewBuild.studyBuild)
        #expect(!reviewBuild.canUploadTelemetry && !reviewBuild.syncAllowed(hasICloudEntitlement: true))
        // Each build carries only its own secrets, even when the owner's file holds all four keys (docs/02).
        let everySecret = [
            "ITA_TELEMETRY_URL": "https://study.example.org", "ITA_STUDY_TOKEN": "study-token",
            "ITA_REVIEW_URL": "https://review.example.org", "ITA_REVIEW_TOKEN": "review-token",
        ]
        let study = try Xcconfig.values("Study.xcconfig", optional: ["Secrets-Study.xcconfig": everySecret])
        #expect(study["ITA_STUDY_TOKEN"] as? String == "study-token")
        #expect(study["ITA_REVIEW_URL"] as? String == "" && study["ITA_REVIEW_TOKEN"] as? String == "")
        let review = try Xcconfig.values("Review.xcconfig", optional: ["Secrets-Review.xcconfig": everySecret])
        #expect(review["ITA_REVIEW_TOKEN"] as? String == "review-token")
        #expect(review["ITA_TELEMETRY_URL"] as? String == "" && review["ITA_STUDY_TOKEN"] as? String == "")
        // A study build never gets it, whatever else is set, nor does any build of the release pack (Release and
        // Study); a Debug UI test can turn it off.
        #expect(!AppConfig(info: ["ITA_REVIEW_MODE": "YES", "ITA_STUDY_BUILD": "YES"]).reviewMode)
        #expect(!AppConfig(info: ["ITA_REVIEW_MODE": "YES", "ITA_PACK": "release"]).reviewMode)
        #expect(!AppConfig(info: ["ITA_REVIEW_MODE": "YES", "ITA_PACK": "Release"]).reviewMode)
        var release = try Xcconfig.values("Release.xcconfig")
        release["ITA_REVIEW_MODE"] = "YES"  // a slip in Release.xcconfig still gives learners no review mode
        #expect(!AppConfig(info: release).reviewMode && self.review(info: release) == nil)
        #expect(AppConfig(info: ["ITA_REVIEW_MODE": "YES", "ITA_PACK": "dev"]).reviewMode)
        #expect(
            ReviewMode(
                config: AppConfig(info: Self.reviewInfo), arguments: [ReviewMode.offArgument], store: nil,
                transport: ReviewServer(), clock: clock, ids: SeededUUIDSource(seed: "x")) == nil)
    }

    @Test func aReleasePackKeepsEveryLockInPlace() async throws {
        let app = await app()
        let review = try #require(review())
        review.attach(isReleasePack: true, index: ReviewFileIndex(metaJSON: nil), menu: ReviewJumpMenu(units: []))
        #expect(!review.isActive)
        let rows = app.courseRows
        #expect(rows.contains { !$0.isOpen })  // a new learner: later units are locked
        #expect(review.unlocked(rows) == rows)
        let launch = try #require(try await app.launch(step: "u02.l1.step-practice"))
        let before = launch.model.position
        review.prepare(launch, at: ReviewJump(step: "u02.l1.step-practice", exercise: "u02.l1.ex07"))
        #expect(launch.model.position == before)  // the learner's resume rules apply
        #expect(launch.scoresCheck(review: review) == false && launch.kind == .lesson)
        let check = try #require(try await app.launch(step: "u02.step-check"))
        #expect(check.scoresCheck(review: review))  // review mode is off: a finished check is scored
    }

    /// A pick from the jump menu opens exactly there; a step opened from Today or the Unit overview resumes where
    /// the learner left it when that is in the step (else its first page), and the answer tap listens either way.
    /// A check paged through isn't scored.
    @Test func aHalfDoneStepResumesAndChecksAreNotScored() async throws {
        let app = await app()
        let review = try #require(review())
        await review.attach(to: app)
        let launch = try #require(try await app.launch(step: "u02.l1.step-practice"))
        let player = launch.model
        let practice = try #require(player.index(ofStep: "u02.l1.step-practice"))
        #expect(player.position != practice)  // a new learner resumes at the lesson's preview
        // The Unit overview's Practice: the learner's resume point is in another step, so Practice's first page.
        review.prepare(launch, at: ReviewJump(step: "u02.l1.step-practice"), exact: false)
        #expect(player.position == practice)
        // Practice part-way through (Today's Continue, the overview again): where it was left.
        _ = player.move(to: practice + 3)
        review.prepare(launch, at: ReviewJump(step: "u02.l1.step-practice"), exact: false)
        #expect(player.position == practice + 3)
        // The jump menu: exactly where it points, even inside the step.
        review.prepare(launch, at: ReviewJump(step: "u02.l1.step-practice"))
        #expect(player.position == practice)
        let payload = try #require(player.bundle.exercises["u02.l1.ex07"])
        guard case .typed(let exercise)? = ExerciseHostModel.make(payload, env: launch.environment, sink: launch.sink)
        else {
            Issue.record("u02.l1.ex07 is a recall exercise")
            return
        }
        exercise.response = "quanto fa"
        exercise.check()
        #expect(review.rejectedAnswer(for: "u02.l1.ex07")?.response == "quanto fa")

        // Paging past the end of the unit check and tapping Done finishes without `checkCompleted`.
        let check = try #require(try await app.launch(step: "u02.step-check"))
        review.prepare(check, at: ReviewJump(step: "u02.step-check"), exact: false)
        #expect(check.kind == .check && !check.scoresCheck(review: review))
        #expect(check.scoresCheck(review: nil))
    }

    @Test func everyUnitIsOpenAndTheJumpMenuListsEveryStep() async throws {
        let app = await app()
        let review = try #require(review())
        await review.attach(to: app)
        #expect(review.isActive)
        #expect(review.unlocked(app.courseRows).allSatisfy { $0.isOpen })
        let unit = try #require(review.menu.units.first)
        #expect(review.menu.units.map(\.id) == ["u02"])  // the mini pack has steps for Unit 2 only
        #expect(unit.title == "Unit 2 · Al bar")
        #expect(unit.groups.map(\.title) == ["Unit 2", "Lesson 1 · Un cappuccino, per favore", "Unit 2"])
        #expect(review.menu.steps.count == 12 && review.menu.steps.allSatisfy { $0.isDraft })
        #expect(review.isDraft("u02.l1.step-story"))
        let practice = try #require(review.menu.steps.first { $0.id == "u02.l1.step-practice" })
        #expect(practice.title == "Practice" && practice.exercises.count == 20)
        #expect(review.menu.steps.first { $0.id == "u02.l1.step-story" }?.title == "Story · Bar Aurora")
        #expect(
            review.menu.search("ex07").map(\.jump) == [
                ReviewJump(step: "u02.l1.step-practice", exercise: "u02.l1.ex07")
            ])
        #expect(review.menu.search("STORY").first?.jump == ReviewJump(step: "u02.l1.step-story"))
        #expect(review.menu.search("  ").isEmpty)
    }

    // MARK: - The acceptance proxy

    @Test func filesACommentOnU02L1Ex07AndExportsAReviewFile() async throws {
        let app = await app()
        let server = ReviewServer()
        let review = try #require(review(server: server))
        await review.attach(to: app)

        // Jump straight to the exercise, as the jump menu does (a new learner would resume at the preview).
        let jump = try #require(review.menu.search("u02.l1.ex07").first?.jump)
        let launch = try #require(try await app.launch(review: jump, in: review))
        let player = launch.model
        launch.sink.stepID = player.currentStep?.id
        #expect(player.current?.page == .exercise("u02.l1.ex07"))
        let payload = try #require(player.currentExercise)

        // The answer key lists every accepted answer, the model answer first.
        let key = AnswerKey(payload)
        #expect(key.sections.map(\.title) == ["Accepted answers"])
        #expect(
            key.sections[0].entries.map(\.text) == [
                "quant'è", "quanto è", "quanto costa", "scusi quant'è", "scusi quanto costa",
            ])
        #expect(key.sections[0].entries[0].note == "model answer")

        // A rejected answer, then "This should be accepted" in the feedback panel.
        guard case .typed(let exercise)? = ExerciseHostModel.make(payload, env: launch.environment, sink: launch.sink)
        else {
            Issue.record("u02.l1.ex07 is a recall exercise")
            return
        }
        exercise.response = "quanto fa"
        exercise.check()
        #expect(exercise.feedback?.tone == .hint)
        let rejected = try #require(review.rejectedAnswer(for: "u02.l1.ex07"))
        #expect(rejected == RejectedAnswer(exerciseID: "u02.l1.ex07", turnID: nil, response: "quanto fa"))
        #expect(!review.isFiled(rejected))
        #expect(review.fileAcceptRequest(rejected, payload: payload)?.quote == "How much is it?")
        #expect(review.isFiled(rejected))
        #expect(review.fileAcceptRequest(rejected, payload: payload) == nil)  // one tap files it once

        // Comment on the same exercise from the review bar.
        let entry = try #require(player.current)
        let targets = review.targets(for: entry, bundle: player.bundle)
        #expect(targets.map(\.id) == ["u02.l1.ex07", "u02.l1.step-practice"])
        let draft = review.commentDraft(targets: targets)
        #expect(draft.target?.id == "u02.l1.ex07" && !draft.canSave)
        draft.verdict = .question
        draft.comment = "Is quanto costa taught by this point?"
        #expect(!draft.canSave)  // a category first
        draft.category = .level
        #expect(review.save(draft) != nil)

        // Long-press on a story line: the sheet opens on that line.
        let story = try #require(player.bundle.texts["u02.l1.story"])
        let line = try #require(story.lines.first { $0.number == 3 })
        let storyEntry = try #require(player.entries.first { $0.page == .story("u02.l1.story") })
        let lineDraft = review.commentDraft(
            targets: review.targets(
                for: storyEntry, bundle: player.bundle, first: ReviewTargets.line(story, line)))
        #expect(lineDraft.target?.id == "u02.l1.story#3" && lineDraft.target?.quote == line.text.text)
        lineDraft.category = .naturalness
        lineDraft.suggestion = "Buongiorno! Un cappuccino, per favore."
        #expect(review.save(lineDraft) != nil)

        // A comment on the unit's opener is about the unit spec: it goes into a `specs` review file.
        let opener = try #require(try await app.launch(review: ReviewJump(step: "u02.step-opener"), in: review))
        let openerTargets = review.targets(for: try #require(opener.model.current), bundle: opener.model.bundle)
        #expect(openerTargets.map(\.id) == ["u02", "u02.step-opener"])
        let openerDraft = review.commentDraft(targets: openerTargets)
        openerDraft.selectedID = "u02.step-opener"
        openerDraft.verdict = .ok
        openerDraft.category = .english
        #expect(review.save(openerDraft) != nil)

        // Export: one review file per scope, each valid against the schema and equal to the shared fixture.
        review.collector.setReviewer("Maria Rossi")
        let urls = try review.exportFiles(to: folder.appendingPathComponent("export"))
        #expect(urls.map(\.lastPathComponent) == ["review-specs-2026-10-06.json", "review-u02-2026-10-06.json"])
        let schema = try Data(
            contentsOf: PayloadFixtures.repoRoot.appendingPathComponent("schemas/review-file.schema.json"))
        for (url, fixture) in zip(urls, ["review-app-specs.json", "review-app-u02.json"]) {
            let data = try Data(contentsOf: url)
            #expect(try ReviewFileSchema(schema).problems(data) == [], "\(url.lastPathComponent)")
            let fixtureURL = PayloadFixtures.repoRoot.appendingPathComponent("pipeline/tests/fixtures/\(fixture)")
            if ProcessInfo.processInfo.environment["ITALIANO_RECORD_REVIEW_FIXTURES"] == "1" {
                try data.write(to: fixtureURL)
            }
            let produced = try JSONDecoder().decode(ReviewFile.self, from: data)
            let expected = try JSONDecoder().decode(ReviewFile.self, from: Data(contentsOf: fixtureURL))
            // Hashes follow the mini pack (`make mini-pack`); everything else must match the fixture exactly.
            #expect(produced.withPlaceholderHashes == expected.withPlaceholderHashes, "\(fixture)")
            // Decoding reads `null` and "" alike: an empty comment must be `null` in the file, as the page writes it.
            func comments(_ d: Data) throws -> [String] {
                let json = try #require(try JSONSerialization.jsonObject(with: d) as? [String: Any])
                return (json["comments"] as? [[String: Any]] ?? []).map { c in
                    c["comment"] is NSNull ? "<null>" : c["comment"] as? String ?? "<missing>"
                }
            }
            #expect(try comments(data) == comments(Data(contentsOf: fixtureURL)), "\(fixture)")
            #expect(try comments(data).contains("<null>"), "\(fixture)")
            #expect(produced.files.values.allSatisfy { $0.count == 64 })
        }

        // Send: the same files, to the review endpoint, once.
        await review.send()
        #expect(review.sendState == .done(ReviewSendResult(sent: 4, failure: nil)))
        #expect(
            server.requests.map(\.url.absoluteString)
                == Array(repeating: "https://review.example.org/v1/review-comments", count: 2))
        #expect(
            server.requests.allSatisfy { $0.headers["Authorization"] == "Bearer review-token" && $0.method == "POST" })
        #expect(review.collector.unsent.isEmpty)
        await review.send()
        #expect(server.requests.count == 2 && review.sendStatus == "Everything was already sent.")
    }

    // MARK: - Pieces

    @Test func sendKeepsCommentsTheServerRefused() async throws {
        let app = await app()
        let server = ReviewServer(statuses: [401])
        let review = try #require(review(server: server))
        await review.attach(to: app)
        review.collector.add(target: "u02.l1.ex08", quote: nil, verdict: .change, category: .english, comment: "x")
        await review.send()
        #expect(review.sendState == .done(ReviewSendResult(sent: 0, failure: .refused(status: 401))))
        #expect(review.sendStatus?.hasPrefix("The review server refused") == true)
        #expect(review.collector.unsent.count == 1)
        server.failNetwork = true
        await review.send()
        #expect(review.sendState == .done(ReviewSendResult(sent: 0, failure: .unreachable)))
        // Without an endpoint or token, Send is off and Export still works.
        let exportOnly = try #require(self.review(info: ["ITA_REVIEW_MODE": "YES"]))
        #expect(!exportOnly.canSend)
        #expect(try review.exportFiles(to: folder.appendingPathComponent("e")).count == 1)
    }

    @Test func pageTargetsAndAConversationTurn() async throws {
        let app = await app()
        let review = try #require(review())
        await review.attach(to: app)
        let lesson = try #require(try await app.launch(review: ReviewJump(step: "u02.l1.step-preview"), in: review))
        let bundle = lesson.model.bundle
        let meet = try #require(lesson.model.current)
        #expect(meet.page == .meet(["w:caffe", "w:cappuccino", "w:cornetto", "w:spremuta", "c:vorrei", "c:quant-e"]))
        #expect(
            review.targets(for: meet, bundle: bundle).map(\.id) == [
                "w:caffe", "w:cappuccino", "w:cornetto", "w:spremuta", "c:vorrei", "c:quant-e", "u02.l1.step-preview",
            ])
        let story = try #require(lesson.model.entries.first { $0.page == .story("u02.l1.story") })
        let storyTargets = review.targets(for: story, bundle: bundle).map(\.id)
        #expect(storyTargets.first == "u02.l1.story" && storyTargets.last == "u02.l1.step-story")
        #expect(
            storyTargets.contains("u02.l1.story#1")
                && storyTargets.count == (bundle.texts["u02.l1.story"]?.lines.count ?? 0) + 2)
        // An exercise with a story line as its source names the line too.
        let ex09 = try #require(lesson.model.entries.first { $0.page == .exercise("u02.l1.ex09") })
        #expect(
            review.targets(for: ex09, bundle: bundle).map(\.id) == [
                "u02.l1.ex09", "u02.l1.story#11", "u02.l1.step-practice",
            ])
        let note = try #require(lesson.model.entries.first { if case .note = $0.page { true } else { false } })
        #expect(review.targets(for: note, bundle: bundle).map(\.id) == ["u02.l1.note", "u02.l1.step-note"])

        // A conversation: the turn on screen comes first; a rejected turn files against the node.
        let conv = try #require(
            try await app.launch(review: ReviewJump(step: "u02.step-conversation-1"), in: review))
        let payload = try #require(conv.model.currentExercise)
        guard case .conversation(let talk)? = ExerciseHostModel.make(payload, env: conv.environment, sink: conv.sink)
        else {
            Issue.record("u02.task.conv1 is a conversation")
            return
        }
        let entry = try #require(conv.model.current)
        #expect(
            review.targets(for: entry, bundle: conv.model.bundle, conversationNode: talk.nodeID).map(\.id) == [
                "u02.task.conv1/n1", "u02.task.conv1", "u02.step-conversation-1",
            ])
        talk.response = "boh"
        talk.submitTyped()
        let rejected = try #require(review.rejectedAnswer(for: "u02.task.conv1"))
        #expect(rejected.target == "u02.task.conv1/n1")
        let filed = try #require(review.fileAcceptRequest(rejected, payload: payload))
        #expect(filed.quote == "Buongiorno! Cosa prende?" && filed.file == "content/units/02-al-bar/task.yaml")
        // A later accepted turn clears it.
        talk.response = "un cappuccino"
        talk.submitTyped()
        #expect(review.rejectedAnswer(for: "u02.task.conv1") == nil)
    }

    @Test func movingBetweenPagesStartsStepsButNeverCompletesThem() async throws {
        let app = await app()
        let review = try #require(review())
        await review.attach(to: app)
        let launch = try #require(
            try await app.launch(review: ReviewJump(step: "u02.l1.step-practice", exercise: "u02.l1.ex01"), in: review))
        let player = launch.model
        let first = try #require(player.index(ofExercise: "u02.l1.ex01"))
        #expect(player.position == first)
        #expect(player.move(to: first + 1) == .init())
        #expect(player.move(to: first - 1) == .init(completed: nil, started: "u02.l1.step-note"))
        #expect(player.move(to: player.entries.count + 5) == .init(completed: nil, started: nil))
        #expect(player.isFinished)
        #expect(player.move(to: 0) == .init(completed: nil, started: "u02.l1.step-preview"))
        #expect(!player.isFinished && player.index(ofStep: "u02.l1.step-use") != nil)
        #expect(player.index(ofExercise: "u02.task.conv1") == nil)
    }

    @Test func answerKeysForOtherFormats() throws {
        let examples = try PayloadFixtures.exercises()
        for (_, p) in examples {
            let key = AnswerKey(p)
            #expect(!key.sections.isEmpty, "\(p.id)")
            #expect(key.sections.allSatisfy { !$0.entries.isEmpty || $0.title.hasPrefix("Turn") }, "\(p.id)")
        }
        let mini = try PayloadFixtures.miniExercise("u02.l1.ex09")
        let near = try #require(AnswerKey(mini).sections.last)
        #expect(near.title == "Near misses")
        #expect(near.entries.map(\.text) == ["amico"])
        #expect(near.entries.first?.note == "not accepted · Sara is a woman. Check the ending.")
        let conv = AnswerKey(try PayloadFixtures.miniExercise("u02.task.conv1"))
        #expect(conv.sections.first?.title == "Turn n1: Buongiorno! Cosa prende?")
        #expect(conv.sections.first?.entries.first?.note == "intent order-drink · goal drink")
        let relay = AnswerKey(try PayloadFixtures.miniExercise("u02.task.relay"))
        #expect(relay.sections.first?.entries.map(\.text) == ["1.60"])
    }

    @Test func theTapKeepsTheLastRejectedAnswer() {
        let tap = ReviewAnswerTap()
        func draft(_ outcome: AttemptOutcome, _ response: String?, turn: String? = nil) -> AttemptDraft {
            AttemptDraft(
                exerciseID: "u02.l1.ex07", turnID: turn, format: .recall, attemptIndex: 1, outcome: outcome,
                targets: [], response: response, mode: .typed, latencyMs: 0, feedbackShown: .none)
        }
        tap.record(draft(.wrong, " quanto fa "))
        #expect(tap.rejected["u02.l1.ex07"]?.response == "quanto fa")
        tap.record(draft(.revealed, nil))
        #expect(tap.rejected["u02.l1.ex07"]?.response == "quanto fa")  // Show answer keeps it
        tap.record(draft(.wrong, ""))
        #expect(tap.rejected["u02.l1.ex07"] == nil)
        tap.record(draft(.wrong, "boh", turn: "n2"))
        #expect(tap.rejected["u02.l1.ex07"]?.target == "u02.l1.ex07/n2")
        tap.record(draft(.almost, "quant'e"))
        #expect(tap.rejected.isEmpty)
    }
}

/// The review endpoint (docs/12 § Review comments): records requests, answers with the given statuses.
final class ReviewServer: HTTPTransport, @unchecked Sendable {
    // @unchecked: every field is guarded by `lock`.
    private let lock = NSLock()
    private var statuses: [Int]
    private var recorded: [HTTPRequestSpec] = []
    private var failing = false

    init(statuses: [Int] = []) { self.statuses = statuses }

    var requests: [HTTPRequestSpec] { lock.withLock { recorded } }
    var failNetwork: Bool {
        get { lock.withLock { failing } }
        set { lock.withLock { failing = newValue } }
    }

    func send(_ request: HTTPRequestSpec) async throws -> Int {
        try lock.withLock {
            recorded.append(request)
            if failing { throw URLError(.notConnectedToInternet) }
            return statuses.isEmpty ? 200 : statuses.removeFirst()
        }
    }
}

extension ReviewFile {
    /// The file with every hash replaced, to compare with a fixture whatever the mini pack's current hashes are.
    var withPlaceholderHashes: ReviewFile {
        var copy = self
        copy.files = files.mapValues { _ in "<hash>" }
        return copy
    }
}

extension PayloadFixtures {
    /// One exercise of the mini pack (`fixtures/packs/mini-payloads.json`).
    static func miniExercise(_ id: String) throws -> ExercisePayload {
        let data = try Data(contentsOf: repoRoot.appendingPathComponent("fixtures/packs/mini-payloads.json"))
        let doc = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let raw = try #require((doc["exercises"] as? [String: Any])?[id])
        return try JSONDecoder().decode(ExercisePayload.self, from: JSONSerialization.data(withJSONObject: raw))
    }
}

/// The ITA_* keys of one build configuration, resolved from App/Config/*.xcconfig as Xcode does (includes in
/// order, later assignments win). Optional includes (`#include?`: the owner's secrets and Signing) are left out
/// unless `optional` supplies their keys, as the owner's gitignored files would.
enum Xcconfig {
    static func values(_ file: String, optional: [String: [String: String]] = [:]) throws -> [String: Any] {
        var out: [String: Any] = [:]
        try read(file, optional: optional, into: &out)
        return out
    }

    private static func read(
        _ file: String, optional: [String: [String: String]], into out: inout [String: Any]
    ) throws {
        let url = PayloadFixtures.repoRoot.appendingPathComponent("App/Config/\(file)")
        for raw in try String(contentsOf: url, encoding: .utf8).split(separator: "\n") {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("//") { continue }
            if line.hasPrefix("#include?") {
                let parts = line.split(separator: "\"")
                if parts.count >= 2, let keys = optional[String(parts[1])] {
                    for (key, value) in keys { out[key] = value }
                }
                continue
            }
            if line.hasPrefix("#include") {
                let parts = line.split(separator: "\"")
                if parts.count >= 2 { try read(String(parts[1]), optional: optional, into: &out) }
                continue
            }
            guard line.hasPrefix("ITA_"), let eq = line.firstIndex(of: "=") else { continue }
            let key = line[..<eq].trimmingCharacters(in: .whitespaces)
            var value = String(line[line.index(after: eq)...])
            if let comment = value.range(of: "//") { value = String(value[..<comment.lowerBound]) }
            out[key] = value.replacingOccurrences(of: "$()", with: "").trimmingCharacters(in: .whitespaces)
        }
    }
}

/// Checks a review file against the parts of `schemas/review-file.schema.json` the app writes: the keys, the
/// required fields, the scope, path and hash patterns, the verdict and category enums, and the date-times. The
/// pipeline's tests validate the committed fixtures with jsonschema itself and import them.
struct ReviewFileSchema {
    let schema: [String: Any]

    init(_ data: Data) throws {
        schema = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private func def(_ path: [String]) -> [String: Any]? {
        var node: Any? = schema
        for key in path { node = (node as? [String: Any])?[key] }
        return node as? [String: Any]
    }

    private func matches(_ value: Any?, pattern: String?) -> Bool {
        guard let s = value as? String, let pattern, let regex = try? Regex(pattern) else { return false }
        return s.firstMatch(of: regex) != nil
    }

    private func isDateTime(_ value: Any?) -> Bool {
        guard let s = value as? String else { return false }
        return ISO8601DateFormatter().date(from: s) != nil
    }

    func problems(_ data: Data) throws -> [String] {
        let file = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        var out: [String] = []
        let properties = Set((schema["properties"] as? [String: Any])?.keys.map { $0 } ?? [])
        let required = schema["required"] as? [String] ?? []
        out += Set(file.keys).subtracting(properties).map { "unknown key \($0)" }
        out += required.filter { file[$0] == nil }.map { "missing \($0)" }
        if file["format"] as? Int != 1 { out.append("format is not 1") }
        if !["page", "app"].contains(file["channel"] as? String ?? "") { out.append("bad channel") }
        if !matches(file["scope"], pattern: def(["$defs", "scope"])?["pattern"] as? String) { out.append("bad scope") }
        if !isDateTime(file["created"]) { out.append("bad created") }
        let pathPattern = def(["$defs", "path"])?["pattern"] as? String
        let hashPattern = def(["$defs", "hash"])?["pattern"] as? String
        for (path, hash) in file["files"] as? [String: Any] ?? [:] {
            if !matches(path, pattern: pathPattern) { out.append("bad file path \(path)") }
            if !matches(hash, pattern: hashPattern) { out.append("bad hash for \(path)") }
        }
        if !(file["signoff"] == nil || file["signoff"] is NSNull) { out.append("the app never signs off") }
        let fields = def(["$defs", "commentFields", "properties"]) ?? [:]
        let commentRequired = def(["$defs", "comment"])?["required"] as? [String] ?? []
        let verdicts = (fields["verdict"] as? [String: Any])?["enum"] as? [Any] ?? []
        let categories = (fields["category"] as? [String: Any])?["enum"] as? [Any] ?? []
        for (n, c) in (file["comments"] as? [[String: Any]] ?? []).enumerated() {
            out += Set(c.keys).subtracting(fields.keys).map { "comments[\(n)]: unknown key \($0)" }
            out += commentRequired.filter { c[$0] == nil }.map { "comments[\(n)]: missing \($0)" }
            if !verdicts.contains(where: { $0 as? String == c["verdict"] as? String }) {
                out.append("comments[\(n)]: bad verdict")
            }
            if !categories.contains(where: { $0 as? String == c["category"] as? String }) {
                out.append("comments[\(n)]: bad category")
            }
            if !matches(c["file"], pattern: pathPattern) { out.append("comments[\(n)]: bad file") }
            if !isDateTime(c["at"]) { out.append("comments[\(n)]: bad at") }
            for key in ["quote", "comment", "suggestion", "response"] where !(c[key] is String || c[key] is NSNull) {
                out.append("comments[\(n)]: \(key) is neither text nor null")
            }
            if (c["id"] as? String ?? "").isEmpty || (c["target"] as? String ?? "").isEmpty {
                out.append("comments[\(n)]: empty id or target")
            }
        }
        return out.sorted()
    }
}
