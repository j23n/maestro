import Foundation
import LearningCore
import Storage

// The final A1 check in the app container (docs/05 § Final A1 check, docs/06 §20, docs/09 § Transcription,
// docs/12 § Final check export): where it is offered, the sitting with its recordings, the score and
// `checkCompleted`, and the examiner export. Platform-neutral, so it compiles and is tested on Linux.

extension AppModel {
    struct FinalCheckLaunch {
        let model: FinalCheckSessionModel
        let sessionID: String
        let startedAt: Int64
        let recordings: SpeakingRecordings
        /// What the sections taken require that the learner hasn't met: the mini-preview shows it before Start.
        let missing: [ItemSkillPair]
    }

    /// The result screen and the examiner export it shares.
    struct FinalCheckOutcome {
        let result: FinalCheckResultContent
        /// The zip in `exports/`, ready for the share sheet; nil when it couldn't be written.
        let export: URL?
    }

    /// `Application Support/Italiano/` (or the folder of the test's learner database).
    var assessmentFilesDirectory: URL? {
        (env.learnerURL ?? (try? LearnerStore.defaultURL()))?.deletingLastPathComponent()
    }

    /// Final-check speaking recordings, on the recording device only (docs/09).
    var recordingsDirectory: URL? { assessmentFilesDirectory?.appendingPathComponent("recordings", isDirectory: true) }

    /// Examiner exports, kept for the share sheet until 30 days after they were made.
    var examinerExportsDirectory: URL? {
        assessmentFilesDirectory?.appendingPathComponent("exports", isDirectory: true)
    }

    /// The final check is offered in the final review unit once it is open (Unit 12 completed), when the pack has
    /// every section written.
    func offersFinalCheck(in unit: UnitID) -> Bool {
        guard let content, let state, content.finalUnit?.id == unit else { return false }
        return FinalCheck.isAvailable(state: state, content: content)
            && FinalCheck.isRunnable(content.finalCheck, content: content)
    }

    /// Loads the sections' exercises (leaving out speaking when the device can't take it), the texts they show or
    /// play, and the session's recordings folder.
    func startFinalCheck() async throws(PackError) -> FinalCheckLaunch? {
        guard let reader, let content, let factory, let final = content.finalCheck,
            FinalCheck.isRunnable(final, content: content), let directory = recordingsDirectory
        else { return nil }
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
        let recordings = SpeakingRecordings(directory: directory, ids: env.ids)
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
    /// score is kept), then writes the examiner export; once the recordings are inside it they are deleted from
    /// their folder (docs/09: until export or 30 days).
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
        let export = ExaminerExport(
            installId: settings.studyInstallId, takenAt: completed.at, tzOffsetMinutes: completed.tzOffsetMin,
            packVersion: content.packVersion, appVersion: Self.appVersion,
            sections: model.sections.map { .init(id: $0.id, title: $0.title, exerciseIds: $0.exerciseIds) },
            result: result, formats: formats, scores: scores, checkAnswers: model.recorder.answers,
            answers: model.log.answers)
        var url: URL?
        do {
            url = try writeExaminerExport(export)
            launch.recordings.delete(model.log.recordingURLs)
        } catch {
            url = nil
        }
        return FinalCheckOutcome(result: FinalCheckResultContent(result: result, titles: titles), export: url)
    }

    /// Leaving mid-check: the `session` event once the sitting began, nothing scored, and the sitting's recordings
    /// deleted (no export will ever hold them).
    func abandonFinalCheck(_ launch: FinalCheckLaunch, activeSeconds: Int) {
        if launch.model.phase != .intro {
            endSession(
                sessionID: launch.sessionID, kind: .final, startedAt: launch.startedAt, activeSeconds: activeSeconds)
        }
        launch.recordings.discardPending()
        launch.recordings.delete(launch.model.log.recordingURLs)
    }

    /// Writes `exports/final-check-<installId>-<date>.zip` (a retake on the same day replaces it).
    func writeExaminerExport(_ export: ExaminerExport) throws -> URL {
        guard let directory = examinerExportsDirectory else { throw CocoaError(.fileNoSuchFile) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let data = try StoredZip.archive(
            try export.entries(), modified: export.takenAt, tzOffsetMinutes: export.tzOffsetMinutes)
        let url = directory.appendingPathComponent(export.fileName)
        try data.write(to: url, options: .atomic)
        return url
    }

    /// The newest examiner export still on this device: the final review unit offers it again.
    var latestExaminerExport: URL? {
        guard let directory = examinerExportsDirectory,
            let files = try? FileManager.default.contentsOfDirectory(
                at: directory, includingPropertiesForKeys: [.contentModificationDateKey])
        else { return nil }
        func modified(_ url: URL) -> Date {
            (try? url.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate ?? .distantPast
        }
        return files.filter { $0.pathExtension == "zip" }.max { modified($0) < modified($1) }
    }

    /// Recordings and exports older than 30 days are deleted (docs/09, docs/12); runs at launch.
    func purgeExpiredRecordings() {
        let now = env.clock.nowMs()
        for directory in [recordingsDirectory, examinerExportsDirectory].compactMap({ $0 }) {
            SpeakingRecordings.purge(directory: directory, nowMs: now)
        }
    }

    /// "1.0 (57)" from the bundle, for the export's README and responses.
    static var appVersion: String? {
        let info = Bundle.main.infoDictionary ?? [:]
        guard let version = info["CFBundleShortVersionString"] as? String else { return nil }
        return (info["CFBundleVersion"] as? String).map { "\(version) (\($0))" } ?? version
    }
}
