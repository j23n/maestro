import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// M8.1, M8.2 through the app container (`AppModel`) on `fixtures/packs/assessment.sqlite`, the mini pack plus
/// placement blocks for Units 1–2, the final review unit and a final check whose pass mark is 6: placement from the
/// offer to "Start there", the offer restored at launch, the final check's sitting, score, `checkCompleted`, the
/// sitting's record, **Export for examiner** through a fake share sheet (docs/12: recordings go only after a
/// completed share), leaving a sitting, and the files going with the learner database (reset, account switch).
@MainActor
@Suite struct AssessmentContainerTests {
    static let packURL = PayloadFixtures.repoRoot.appendingPathComponent("fixtures/packs/assessment.sqlite")
    let folder = FileManager.default.temporaryDirectory
        .appendingPathComponent("italiano-assess-\(UUID().uuidString)", isDirectory: true)
    let clock = FixedClock(ms: 1_791_271_800_000, tzOffsetMinutes: 120)  // Tue 6 Oct 2026, 09:30 in Rome

    func launch(_ seed: String = "a") async throws -> AppModel {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let app = AppModel(
            env: .init(
                packURL: Self.packURL, learnerURL: folder.appendingPathComponent("learner.sqlite"), clock: clock,
                ids: SeededUUIDSource(seed: seed), platform: .iPhone))
        await app.start()
        try #require(app.phase == .ready)
        return app
    }

    func events(_ app: AppModel) async throws -> [Event] {
        await app.settle()
        return try await #require(app.store).events()
    }

    func onboard(_ app: AppModel, beginner: Bool, name: String = "", country: String? = nil, consent: Bool? = nil) {
        app.completeOnboarding(
            .init(
                reason: nil, name: name, forms: .both, country: country, goal: 5, beginner: beginner, consent: consent))
    }

    // MARK: - Placement

    @Test func placementRunsFromTheOfferToStartThere() async throws {
        let app = try await launch()
        #expect(app.canRunPlacement)
        onboard(app, beginner: false)
        #expect(app.placementPending)
        let launch = try #require(try await app.startPlacement())
        #expect(launch.model.session.maximumCount == 10)
        launch.model.start()
        // Unit 1's block all right, Unit 2's one of five: placement stops there and starts the learner at Unit 2.
        while launch.model.phase == .playing {
            guard case .choice(let m) = launch.model.host else {
                Issue.record("placement items are choice questions here")
                return
            }
            let right = launch.model.session.results.isEmpty || launch.model.session.position == 0
            m.select(right ? m.correctIndex : (m.correctIndex + 1) % m.options.count)
            launch.model.advance()
        }
        #expect(launch.model.startUnit == "u02")
        let completion = try #require(launch.model.completion)
        app.finishPlacement(completion, launch: launch, activeSeconds: 120)
        #expect(!app.placementPending)

        let events = try await events(app)
        #expect(events.suffix(3).map(\.type) == ["session", "placementCompleted", "introduced"])
        let sessions = events.compactMap { e -> SessionPayload? in
            if case .session(let s) = e.payload { s } else { nil }
        }
        #expect(sessions.count == 1)
        #expect(sessions.first?.kind == .placement && sessions.first?.sessionId == launch.sessionID)
        #expect(sessions.first?.activeSeconds == 120)
        let attempts = events.compactMap { e -> AttemptPayload? in
            if case .attempt(let a) = e.payload { a } else { nil }
        }
        #expect(attempts.count == 10)
        #expect(attempts.allSatisfy { $0.context == .placement && $0.sessionId == launch.sessionID })
        let state = try #require(app.state)
        #expect(state.placement?.startUnit == "u02")
        #expect(state.unitState("u00") == .skipped && state.unitState("u01") == .skipped)
        #expect(state.unitState("u02") == .available)
        #expect(state.introductions.values.allSatisfy { $0.via == .placement })
        #expect(app.today?.review.catchUp != nil)
    }

    @Test func startFromTheBeginningOnTheIntroWritesNoSession() async throws {
        let app = try await launch()
        onboard(app, beginner: false)
        let launch = try #require(try await app.startPlacement())
        #expect(!launch.model.hasStarted)
        app.startFromTheBeginning(launch: launch, activeSeconds: 5)
        #expect(!app.placementPending)
        let events = try await events(app)
        #expect(!events.contains { $0.type == "session" })
        #expect(events.last?.type == "placementCompleted")
        #expect(app.state?.placement?.startUnit == "u00" && app.state?.introductions.isEmpty == true)
    }

    /// docs/05 § Placement, point 7: the latest `onboardingCompleted` decides whether placement is offered again.
    @Test func theOfferComesBackAtLaunchFromTheLatestOnboarding() async throws {
        let first = try await launch("a")
        onboard(first, beginner: false)
        await first.settle()
        let second = try await launch("b")  // the app was closed during placement
        #expect(second.isOnboarded && second.placementPending)
        onboard(second, beginner: true)  // onboarding again (another device, a reset) says "No"
        #expect(!second.placementPending)
        await second.settle()
        let third = try await launch("c")
        #expect(!third.placementPending)
        onboard(third, beginner: false)
        await third.settle()
        let fourth = try await launch("d")
        #expect(fourth.placementPending)
        // Once anything is started, it isn't offered any more.
        fourth.startFromTheBeginning(launch: nil, activeSeconds: 0)
        await fourth.settle()
        let fifth = try await launch("e")
        #expect(!fifth.placementPending)
    }

    // MARK: - Final check

    struct Played {
        let launch: AppModel.FinalCheckLaunch
        let recognizer: FakeSpeechRecognizer
    }

    /// Plays the final check as FinalCheckHost does: every choice right, the form with a wrong nationality, the
    /// talk task spoken (and recorded), or `stopAt` an exercise.
    func play(_ app: AppModel, stopAt: ExerciseID? = nil) async throws -> Played {
        let launch = try #require(try await app.startFinalCheck())
        if !launch.missing.isEmpty { app.introduceForFinalCheck(launch.missing) }  // the mini-preview's Continue
        let recognizer = FakeSpeechRecognizer(
            availability: .available,
            scripted: [
                SpeechResult(
                    transcript: "Buongiorno! Vorrei un cappuccino e una spremuta. Quant'è?", alternatives: [],
                    confidence: 0.9)
            ])
        recognizer.recordingStub = Data("m4a bytes".utf8)
        let speech = SpeechCapture(recognizer: recognizer)
        speech.recordingDestination = { [model = launch.model] in model.recordingDestination() }
        launch.model.start()
        while launch.model.phase == .playing, launch.model.currentExercise != stopAt {
            switch launch.model.host {
            case .choice(let m):
                m.select(m.correctIndex)
            case .writing(let m):
                m.fieldValues = ["Anna", "inglese"]
                m.submit()
            case .talk(let m):
                let heard = try #require(await speech.capture(expected: [m.talk.model.text]))
                m.submitSpoken(heard)
            default:
                Issue.record("unexpected item \(String(describing: launch.model.currentExercise))")
            }
            launch.model.advance()
        }
        return Played(launch: launch, recognizer: recognizer)
    }

    /// A learner at the final review unit: onboarded (with a name and country the answers never use), study
    /// consent, speech on, jumped to `u99`.
    func finalReviewLearner(_ seed: String = "a") async throws -> AppModel {
        let app = try await launch(seed)
        onboard(app, beginner: true, name: "Zebedee", country: "jp", consent: true)
        app.canSpeak = true
        try await app.debugJump(to: "u99")
        return app
    }

    func sittingFiles(_ app: AppModel, _ sittingId: String) throws -> [String] {
        let files = try #require(app.finalCheckFiles)
        let names = try? FileManager.default.contentsOfDirectory(atPath: files.sittingDirectory(sittingId).path)
        return (names ?? []).sorted()
    }

    @Test func theFinalCheckIsScoredKeptAndExportedOnlyWhenTheShareCompletes() async throws {
        let app = try await finalReviewLearner()
        #expect(app.offersFinalCheck(in: "u99") && !app.offersFinalCheck(in: "u02"))
        let played = try await play(app)
        let launch = played.launch
        #expect(launch.model.phase == .finished)
        app.endSession(sessionID: launch.sessionID, kind: .final, startedAt: launch.startedAt, activeSeconds: 600)
        let before = app.finalCheckFilesChanged
        let outcome = try #require(app.completeFinalCheck(launch))
        #expect(app.finalCheckFilesChanged > before)

        // The pack's pass mark (6): writing scored 1 of 2 fields → 6 of 12, which passes here (7 would not).
        #expect(outcome.result.sections.map(\.score) == ["12 of 12", "12 of 12", "12 of 12", "6 of 12", "12 of 12"])
        #expect(outcome.result.indicativePass)
        #expect(outcome.result.headline == "You reached the indicative A1 pass in every section.")
        #expect(outcome.result.passRule == "Indicative pass: 6 of 12 in every section.")

        // checkCompleted (kind final) after the session; the final review unit is completed.
        let events = try await events(app)
        let completed = try #require(events.last)
        guard case .checkCompleted(let payload) = completed.payload else {
            Issue.record("the last event is \(completed.type)")
            return
        }
        #expect(payload.kind == .final && payload.passed)
        #expect(events.dropLast().last?.type == "session")
        #expect(app.state?.unitState("u99") == .completed)

        // Kept for the export: the record and the recording, nothing zipped or shared yet.
        let export = try #require(outcome.export)
        #expect(export.sittingId == launch.sessionID && export.checkCompletedEventId == completed.id)
        #expect(export.responses.passMarkPerSection == 6)
        let attemptId = try #require(launch.model.log.answers["fin.speaking.01"]?.first?.attemptId)
        #expect(try sittingFiles(app, launch.sessionID) == ["fin.speaking.01-\(attemptId).m4a", "sitting.json"])
        let files = try #require(app.finalCheckFiles)
        // No zip until Export for examiner is tapped (the folder exists, empty and excluded from backups).
        #expect(((try? FileManager.default.contentsOfDirectory(atPath: files.exportsDirectory.path)) ?? []).isEmpty)
        #expect(await app.pendingExaminerExport() == export)

        // A cancelled share: the zip goes, the recordings stay so the learner can try again.
        let sharing = FakeExportSharing(outcome: .cancelled)
        #expect(await app.exportForExaminer(export, sharing: sharing) == .cancelled)
        let installId = try #require(app.settings.studyInstallId)
        #expect(sharing.shared.map(\.name) == ["final-check-\(installId)-2026-10-06-0930.zip"])
        #expect((try? FileManager.default.contentsOfDirectory(atPath: files.exportsDirectory.path)) ?? [] == [])
        #expect(try sittingFiles(app, launch.sessionID).count == 2)
        #expect(await app.pendingExaminerExport() == export)

        // What was shared: the documented files, and no profile data (docs/12).
        let zip = try ZipReader.read(try #require(sharing.shared.first?.data))
        #expect(
            zip.map(\.path) == [
                "README.txt", "responses.json", "writing/fin.writing.01.txt",
                "speaking/fin.speaking.01-\(attemptId).m4a",
            ])
        #expect(zip.allSatisfy(\.crcMatches) && zip[3].data == Data("m4a bytes".utf8))
        let readme = String(decoding: zip[0].data, as: UTF8.self)
        let responses = String(decoding: zip[1].data, as: UTF8.self)
        #expect(readme.contains("Install ID: \(installId)"))
        #expect(readme.contains("indicative pass: 6 of 12 in every section"))
        for profileData in ["Zebedee", "Japan", "Giappone", "giapponese", "\"jp\""] {
            #expect(!readme.contains(profileData) && !responses.contains(profileData), "\(profileData) leaked")
        }
        // The documented keys; `app.version` is absent here because the test runner's bundle has no version.
        let keys = try FinalCheckTests.keys(zip[1].data)
        let documented = try FinalCheckTests.documentedKeys()
        #expect(keys.isSubset(of: documented) && documented.subtracting(keys) == ["app.version"])

        // A completed share is the successful export: the recordings, the record and the zip go.
        sharing.outcome = .completed
        #expect(await app.exportForExaminer(export, sharing: sharing) == .shared)
        #expect(sharing.shared.count == 2 && sharing.shared[1].data == sharing.shared[0].data)
        #expect(try sittingFiles(app, launch.sessionID).isEmpty)
        #expect(!FileManager.default.fileExists(atPath: files.sittingDirectory(launch.sessionID).path))
        #expect((try? FileManager.default.contentsOfDirectory(atPath: files.exportsDirectory.path)) ?? [] == [])
        #expect(await app.pendingExaminerExport() == nil)
        #expect(await app.exportForExaminer(export, sharing: sharing) == .failed)  // nothing left to export
        #expect(sharing.shared.count == 2)
    }

    @Test func introducingForTheFinalCheckUsesCatchUp() async throws {
        let app = try await launch()
        onboard(app, beginner: true)
        let launch = try #require(try await app.startFinalCheck())
        #expect(!launch.missing.isEmpty)  // a new learner has met none of what the items require
        app.introduceForFinalCheck(launch.missing)
        let events = try await events(app)
        guard case .introduced(let payload)? = events.last?.payload else {
            Issue.record("no introduced event")
            return
        }
        #expect(payload.via == .catchup && payload.stepId == nil)
        let state = try #require(app.state)
        #expect(launch.missing.allSatisfy { state.introductions[$0]?.via == .catchup })
        let content = try #require(app.content)
        let final = try #require(content.finalCheck)
        #expect(
            FinalCheck.missingRequirements(final, excluded: launch.model.excluded, state: state, content: content)
                .isEmpty)
    }

    @Test func leavingASittingDeletesItsRecordingsAndWritesASessionOnlyAfterStart() async throws {
        let app = try await finalReviewLearner()
        // Not now on the intro: nothing written, nothing kept.
        let unstarted = try #require(try await app.startFinalCheck())
        app.abandonFinalCheck(unstarted, activeSeconds: 3)
        let before = try await events(app)
        #expect(!before.contains { $0.type == "session" })
        #expect(try sittingFiles(app, unstarted.sessionID).isEmpty)

        // Leaving after the spoken answer: the session event, no score, the recording deleted.
        let played = try await play(app)
        let launch = played.launch
        #expect(try sittingFiles(app, launch.sessionID).count == 1)
        app.abandonFinalCheck(launch, activeSeconds: 30)
        let after = try await events(app)
        let sessions = after.compactMap { e -> SessionPayload? in
            if case .session(let s) = e.payload { s } else { nil }
        }
        #expect(sessions.map(\.sessionId) == [launch.sessionID] && sessions.first?.kind == .final)
        #expect(!after.contains { $0.type == "checkCompleted" })
        #expect(played.recognizer.recordedURLs.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
        let folderLeft = try #require(app.finalCheckFiles).sittingDirectory(launch.sessionID)
        #expect(!FileManager.default.fileExists(atPath: folderLeft.path))
        #expect(await app.pendingExaminerExport() == nil)
    }

    // MARK: - The files go with the learner database (M3)

    func completedSitting(_ app: AppModel) async throws -> ExaminerExport {
        let played = try await play(app)
        let export = try #require(app.completeFinalCheck(played.launch)?.export)
        await app.settle()
        return export
    }

    @Test func resettingProgressDeletesTheSittings() async throws {
        let app = try await finalReviewLearner()
        let export = try await completedSitting(app)
        #expect(await app.pendingExaminerExport() == export)
        try await app.debugResetLocalData()
        let files = try #require(app.finalCheckFiles)
        #expect(files.sittings().isEmpty)
        #expect(!FileManager.default.fileExists(atPath: files.sittingsDirectory.path))
        #expect(await app.pendingExaminerExport() == nil)
    }

    @Test func anotherLearnerDatabaseNeverSeesThePreviousSittings() async throws {
        let app = try await finalReviewLearner()
        _ = try await completedSitting(app)
        let content = try #require(app.content)
        let other = try await LearnerStore.open(
            url: folder.appendingPathComponent("other-account.sqlite"), content: content, clock: clock,
            ids: SeededUUIDSource(seed: "other"))
        await app.replaceStore(other)  // an iCloud account switch
        #expect(try #require(app.finalCheckFiles).sittings().isEmpty)
        #expect(await app.pendingExaminerExport() == nil)
    }

    /// The same database reopened (archiving failed during an account switch): its sittings stay.
    @Test func reopeningTheSameDatabaseKeepsItsSittings() async throws {
        let app = try await finalReviewLearner()
        let export = try await completedSitting(app)
        let content = try #require(app.content)
        let same = try await LearnerStore.open(
            url: folder.appendingPathComponent("learner.sqlite"), content: content, clock: clock,
            ids: SeededUUIDSource(seed: "same"))
        await app.replaceStore(same)
        #expect(await app.pendingExaminerExport() == export)
    }

    /// The 30 days run out while the app stays open (a Mac left running for weeks): the sitting is neither offered
    /// nor exported, and goes when the app becomes active again.
    @Test func aSittingPastThirtyDaysIsDeletedWhileTheAppRuns() async throws {
        let app = try await finalReviewLearner()
        let export = try await completedSitting(app)
        let files = try #require(app.finalCheckFiles)
        clock.advance(byMs: 29 * 86_400_000)
        app.deleteExpiredFinalChecks()
        #expect(files.sittings() == [export])
        clock.advance(byMs: 2 * 86_400_000)
        let sharing = FakeExportSharing(outcome: .completed)
        #expect(await app.exportForExaminer(export, sharing: sharing) == .failed)
        #expect(sharing.shared.isEmpty && files.sittings().isEmpty)

        let second = try await completedSitting(app)
        clock.advance(byMs: 31 * 86_400_000)
        #expect(await app.pendingExaminerExport() == nil)
        #expect(!files.sittings().contains(second))

        let third = try await completedSitting(app)
        clock.advance(byMs: 31 * 86_400_000)
        app.deleteExpiredFinalChecks()
        #expect(!files.sittings().contains(third))
    }

    /// Each share builds its zip in its own folder, so ending one share never deletes another's file.
    @Test func overlappingSharesKeepTheirOwnZips() async throws {
        let app = try await finalReviewLearner()
        let export = try await completedSitting(app)
        let files = try #require(app.finalCheckFiles)
        let first = try files.writeZip(export)
        let second = try files.writeZip(export)
        #expect(first != second && first.lastPathComponent == second.lastPathComponent)
        files.deleteZip(first)
        #expect(!FileManager.default.fileExists(atPath: first.path))
        #expect(FileManager.default.fileExists(atPath: second.path))
        files.deleteZip(second)
        let left = (try? FileManager.default.contentsOfDirectory(atPath: files.exportsDirectory.path)) ?? []
        #expect(left.isEmpty)
    }

    /// Progress reset on another device erases this database through sync, without the app's reset: the sitting is
    /// never offered, and goes when it is looked up or at the next launch.
    @Test func aSittingWhoseEventIsGoneIsDeletedWhenFound() async throws {
        let app = try await finalReviewLearner()
        let export = try await completedSitting(app)
        let second = try await finalReviewLearner("b")  // still this learner: the sitting stays at launch
        #expect(await second.pendingExaminerExport() == export)
        try await #require(app.store).eraseProgress()
        let files = try #require(app.finalCheckFiles)
        #expect(files.sittings() == [export])
        #expect(await app.pendingExaminerExport() == nil)
        #expect(files.sittings().isEmpty)

        let orphan = try await completedSitting(second)
        try await #require(second.store).eraseProgress()
        _ = try await launch("c")  // the launch sweep
        #expect(!files.sittings().contains(orphan))
    }
}
