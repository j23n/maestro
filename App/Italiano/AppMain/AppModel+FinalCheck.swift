import Foundation
import LearningCore
import Storage

// The final A1 check in the app container (docs/05 § Final A1 check, docs/06 §20, docs/09 § Transcription,
// docs/12 § Final check export): where it is offered, the sitting with its recordings, the score and
// `checkCompleted`, the sitting's record, and **Export for examiner**. Platform-neutral, so it compiles and is
// tested on Linux.

extension AppModel {
    struct FinalCheckLaunch {
        let model: FinalCheckSessionModel
        let sessionID: String
        let startedAt: Int64
        let recordings: SpeakingRecordings
        /// What the sections taken require that the learner hasn't met: the mini-preview shows it before Start.
        let missing: [ItemSkillPair]
    }

    /// The result screen and the sitting it can export.
    struct FinalCheckOutcome {
        let result: FinalCheckResultContent
        /// The sitting's record, kept with its recordings for **Export for examiner**; nil when it couldn't be
        /// saved on this device.
        let export: ExaminerExport?
    }

    /// How **Export for examiner** ended.
    enum ExaminerExportResult: Sendable, Equatable {
        /// The share completed: the zip, the recordings and the sitting's record are deleted.
        case shared
        /// The learner closed the share sheet (or the service failed): the zip is deleted, the recordings stay so
        /// they can export again until the 30 days are up.
        case cancelled
        /// The zip couldn't be made, or the sitting is no longer on this device.
        case failed
    }

    /// `Application Support/Italiano/` (or the folder of the test's learner database).
    var assessmentFilesDirectory: URL? {
        (env.learnerURL ?? (try? LearnerStore.defaultURL()))?.deletingLastPathComponent()
    }

    /// Final-check sittings (recordings and records) and the zips in the share sheet, on this device only.
    var finalCheckFiles: FinalCheckFiles? { assessmentFilesDirectory.map(FinalCheckFiles.init(root:)) }

    /// The final check is offered in the final review unit once it is open (Unit 12 completed), when the pack has
    /// every section written.
    func offersFinalCheck(in unit: UnitID) -> Bool {
        guard let content, let state, content.finalUnit?.id == unit else { return false }
        return FinalCheck.isAvailable(state: state, content: content)
            && FinalCheck.isRunnable(content.finalCheck, content: content)
    }

    /// Loads the sections' exercises (leaving out speaking when the device can't take it), the texts they show or
    /// play, and the sitting's recordings folder (`final-check/<sessionId>/`).
    func startFinalCheck() async throws(PackError) -> FinalCheckLaunch? {
        guard let reader, let content, let factory, let final = content.finalCheck,
            FinalCheck.isRunnable(final, content: content), let files = finalCheckFiles
        else { return nil }
        files.prepare()  // the folders exist, excluded from backups, before the first recording
        var titles: [String: String] = [:]
        if case .final(_, let sections)? = try await reader.assessment(.final) {
            for s in sections { titles[s.id] = s.titleEn }
        }
        let sections = final.sections.map {
            FinalCheckSessionModel.Section(
                id: $0.id, title: titles[$0.id] ?? $0.id.capitalized, exerciseIds: $0.exerciseIds)
        }
        let excluded = canSpeak ? [] : FinalCheck.speechOnlySections(final, content: content)
        let bundle = try await AssessmentLoader.bundle(
            id: "final", title: FinalCheckCopy.title, unit: content.finalUnit?.id ?? "u99",
            exerciseIDs: sections.filter { !excluded.contains($0.id) }.flatMap(\.exerciseIds), reader: reader)
        let sessionID = env.ids.next()
        let recordings = SpeakingRecordings(directory: files.sittingDirectory(sessionID), ids: env.ids)
        let log = FinalCheckLog(recordings: recordings)
        let sink = EventAttemptSink(factory: factory, context: .final, sessionID: sessionID) { [weak self] e in
            log.append(e)
            self?.write(e)
        }
        let clock = env.clock
        let environment = ExerciseEnvironment(
            context: .final, profile: profile, knownForms: knownForms, nowMs: { clock.nowMs() }, canSpeak: canSpeak)
        let model = FinalCheckSessionModel(
            sections: sections, excluded: excluded, bundle: bundle, env: environment, sink: sink, log: log)
        let missing =
            state.map { FinalCheck.missingRequirements(final, excluded: excluded, state: $0, content: content) } ?? []
        return FinalCheckLaunch(
            model: model, sessionID: sessionID, startedAt: env.clock.nowMs(), recordings: recordings,
            missing: missing)
    }

    /// The mini-preview's Continue before the final check: the missing pairs are introduced `via: catchup`.
    func introduceForFinalCheck(_ pairs: [ItemSkillPair]) {
        guard let factory, let e = factory.introduced(pairs, via: .catchup) else { return }
        write(e)
    }

    /// Scores the sitting and writes `checkCompleted` (kind `final`: the final review unit completes, the best
    /// score is kept), then keeps the sitting's record next to its recordings for **Export for examiner**. Nothing
    /// is zipped or shared yet (docs/12). If the record can't be saved, the recordings can never be exported, so
    /// they go at once.
    func completeFinalCheck(_ launch: FinalCheckLaunch) -> FinalCheckOutcome? {
        guard let content, let factory, let final = content.finalCheck else { return nil }
        let model = launch.model
        let result = CheckScoring.scoreFinal(
            final, answers: model.recorder.answers, excludedSections: model.excluded, content: content)
        let completed = factory.checkCompleted(result.payload)
        write(completed)
        launch.recordings.discardPending()
        let titles = Dictionary(model.sections.map { ($0.id, $0.title) }, uniquingKeysWith: { a, _ in a })
        var formats: [ExerciseID: ExerciseFormat] = [:]
        var scores: [ExerciseID: Double] = [:]
        for id in final.exerciseIds {
            guard let e = content.exercise(id) else { continue }
            formats[id] = e.format
            scores[id] = Double(e.score)
        }
        let record = ExaminerExport(
            sittingId: launch.sessionID, checkCompletedEventId: completed.id, installId: settings.studyInstallId,
            takenAt: completed.at, tzOffsetMinutes: completed.tzOffsetMin, packVersion: content.packVersion,
            appVersion: Self.appVersion, passMarkPerSection: final.indicativePassPerSection,
            sections: model.sections.map { .init(id: $0.id, title: $0.title, exerciseIds: $0.exerciseIds) },
            result: result, formats: formats, scores: scores, checkAnswers: model.recorder.answers,
            answers: model.log.answers)
        var export: ExaminerExport?
        do {
            guard let files = finalCheckFiles else { throw CocoaError(.fileNoSuchFile) }
            try files.save(record)
            export = record
        } catch {
            finalCheckFiles?.deleteSitting(launch.sessionID)
        }
        finalCheckFilesChanged += 1
        return FinalCheckOutcome(
            result: FinalCheckResultContent(
                result: result, titles: titles, passMark: final.indicativePassPerSection),
            export: export)
    }

    /// Leaving mid-check: the `session` event once the sitting began, nothing scored, and the sitting's folder
    /// with its recordings deleted (no export will ever hold them).
    func abandonFinalCheck(_ launch: FinalCheckLaunch, activeSeconds: Int) {
        if launch.model.phase != .intro {
            endSession(
                sessionID: launch.sessionID, kind: .final, startedAt: launch.startedAt, activeSeconds: activeSeconds)
        }
        launch.recordings.discardPending()
        launch.recordings.delete(launch.model.log.recordingURLs)
        finalCheckFiles?.deleteSitting(launch.sessionID)
        finalCheckFilesChanged += 1
    }

    /// **Export for examiner** (docs/12): builds the zip in `exports/` and hands it to the share sheet. A completed
    /// share is the successful export: the zip, the recordings and the sitting's record are deleted (docs/09: kept
    /// until a successful export or 30 days). Any other ending deletes only the zip, so the learner can try again.
    func exportForExaminer(_ export: ExaminerExport, sharing: any ExportSharing) async -> ExaminerExportResult {
        guard let files = finalCheckFiles, files.hasSitting(export.sittingId) else { return .failed }
        if files.isExpired(export, nowMs: env.clock.nowMs()) {
            files.deleteSitting(export.sittingId)
            finalCheckFilesChanged += 1
            return .failed
        }
        switch await belongsToThisLearner(export) {
        case true?: break
        case false?:
            files.deleteSitting(export.sittingId)  // another learner database's sitting goes when it is found
            finalCheckFilesChanged += 1
            return .failed
        case nil: return .failed
        }
        let zip: URL
        do {
            zip = try files.writeZip(export)
        } catch {
            return .failed
        }
        let outcome = await sharing.share(zip)
        files.deleteZip(zip)
        guard outcome == .completed else { return .cancelled }
        files.deleteSitting(export.sittingId)
        finalCheckFilesChanged += 1
        return .shared
    }

    /// The newest sitting this device can still export, for the final review unit. Sittings whose
    /// `checkCompleted` the open learner database doesn't hold (progress reset elsewhere, another iCloud account)
    /// are deleted on the way.
    func pendingExaminerExport() async -> ExaminerExport? {
        guard let files = finalCheckFiles else { return nil }
        if files.deleteExpired(nowMs: env.clock.nowMs()) > 0 { finalCheckFilesChanged += 1 }
        for export in files.sittings() {
            switch await belongsToThisLearner(export) {
            case true?: return export
            case false?: files.deleteSitting(export.sittingId)
            case nil: continue  // the database couldn't be read: keep it
            }
        }
        return nil
    }

    /// Whether the open learner database holds the sitting's `checkCompleted` event (nil: unknown, because no
    /// database is open or it couldn't be read).
    private func belongsToThisLearner(_ export: ExaminerExport) async -> Bool? {
        guard let store else { return nil }
        await settle()
        do {
            return try await store.eventRow(id: export.checkCompletedEventId) != nil
        } catch {
            return nil
        }
    }

    /// Progress reset or another learner database (an iCloud account switch): no sitting, recording or zip of the
    /// previous progress stays on the device.
    func deleteFinalCheckFiles() {
        finalCheckFiles?.deleteAll()
        finalCheckFilesChanged += 1
    }

    /// At launch: sittings older than 30 days, unfinished sittings and leftover zips are deleted (docs/09, docs/12),
    /// then sittings another learner database left behind. After a recovery the fresh database doesn't hold the
    /// sittings' events until sync brings them back, so that last sweep waits for the next launch.
    func purgeFinalCheckFiles() async {
        guard let files = finalCheckFiles else { return }
        files.purge(nowMs: env.clock.nowMs())
        guard recoveryNotice == nil else { return }
        await deleteForeignSittings()
    }

    /// Whenever the app becomes active (it may stay open for weeks): sittings past 30 days go. A sitting in progress
    /// and a zip in the share sheet are never touched.
    func deleteExpiredFinalChecks() {
        if finalCheckFiles?.deleteExpired(nowMs: env.clock.nowMs()) ?? 0 > 0 { finalCheckFilesChanged += 1 }
    }

    /// Sittings whose `checkCompleted` the open database doesn't hold (another iCloud account's, or progress reset
    /// elsewhere) are deleted.
    func deleteForeignSittings() async {
        guard let files = finalCheckFiles else { return }
        var removed = false
        for export in files.sittings() where await belongsToThisLearner(export) == false {
            files.deleteSitting(export.sittingId)
            removed = true
        }
        if removed { finalCheckFilesChanged += 1 }
    }

    /// "1.0 (57)" from the bundle, for the export's README and responses.
    static var appVersion: String? {
        let info = Bundle.main.infoDictionary ?? [:]
        guard let version = info["CFBundleShortVersionString"] as? String else { return nil }
        return (info["CFBundleVersion"] as? String).map { "\(version) (\($0))" } ?? version
    }
}
