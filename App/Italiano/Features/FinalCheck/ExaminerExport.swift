import Foundation
import LearningCore

/// The examiner export of a final A1 check (docs/12 § Final check export). When the check ends, the app keeps this
/// record of the sitting (`sitting.json` in the sitting's folder, `FinalCheckFiles`) next to its recordings; only
/// **Export for examiner** builds `final-check-<installId>-<date>-<time>.zip` from it, holding exactly
///
/// - `responses.json`: every item with the learner's answers, its automatic score, and the section totals;
/// - `writing/<exerciseId>.txt`: the text of each writing task;
/// - `speaking/<exerciseId>-<attemptId>.m4a`: the speaking section's recordings, one per spoken answer (a
///   conversation has one per turn);
/// - `README.txt`: what the archive is, and the install ID.
///
/// Built from the sitting's own `attempt` events, so the archive says exactly what the event log says. No name,
/// country or other profile data goes in. Platform-neutral and tested; `ExportSharing` hands the zip to the share
/// sheet.
struct ExaminerExport: Sendable, Equatable, Codable {
    struct Section: Sendable, Equatable {
        let id: String
        let title: String
        let exerciseIds: [ExerciseID]
    }

    /// One recorded answer: an `attempt` event of the sitting, and the file name of its recording in the sitting's
    /// folder if it was spoken.
    struct Answer: Sendable, Equatable {
        let attemptId: String
        let attempt: AttemptPayload
        let recording: String?
    }

    // MARK: responses.json

    struct Responses: Codable, Equatable, Sendable {
        struct App: Codable, Equatable, Sendable {
            let version: String?
            let pack: String
        }

        struct SectionTotal: Codable, Equatable, Sendable {
            let id: String
            let title: String
            let points: Double
            let max: Double
            let passed: Bool
            /// The device couldn't take it (speaking without speech recognition); not scored.
            let excluded: Bool
        }

        struct Item: Codable, Equatable, Sendable {
            let exerciseId: String
            let section: String
            let format: String
            let score: Double
            let earned: Double
            var answers: [AnswerRecord]
            /// `writing/<exerciseId>.txt` for writing tasks.
            let writingFile: String?
        }

        struct AnswerRecord: Codable, Equatable, Sendable {
            let attemptId: String
            let turnId: String?
            let outcome: String
            let mode: String
            /// The typed text, the chosen option, or the speech transcript.
            let response: String?
            let latencyMs: Int
            /// `speaking/<exerciseId>-<attemptId>.m4a` for spoken answers.
            var recording: String?
        }

        let schema: Int
        let kind: String
        let installId: String?
        let takenAt: String
        let app: App
        let indicativePass: Bool
        /// The pack's `indicativePassPerSection` (docs/05 § Final A1 check).
        let passMarkPerSection: Double
        let sections: [SectionTotal]
        var items: [Item]
    }

    /// The sitting: its `session` ID, which names its folder.
    let sittingId: String
    /// The sitting's `checkCompleted` event: the export belongs to the learner database that holds it.
    let checkCompletedEventId: String
    /// When the check was completed, and the learner's UTC offset then.
    let takenAt: Int64
    let tzOffsetMinutes: Int
    /// `responses.json` as the check ended: each spoken answer names its recording.
    let responses: Responses

    /// Scores and answers of a finished sitting; `answers` are its attempts per exercise, in the order they were
    /// made, and `checkAnswers` what the check scored for each exercise.
    init(
        sittingId: String, checkCompletedEventId: String, installId: String?, takenAt: Int64, tzOffsetMinutes: Int,
        packVersion: String, appVersion: String?, passMarkPerSection: Double, sections: [Section],
        result: FinalCheckResult, formats: [ExerciseID: ExerciseFormat], scores: [ExerciseID: Double],
        checkAnswers: [ExerciseID: CheckAnswer], answers: [ExerciseID: [Answer]]
    ) {
        self.sittingId = sittingId
        self.checkCompletedEventId = checkCompletedEventId
        self.takenAt = takenAt
        self.tzOffsetMinutes = tzOffsetMinutes
        var items: [Responses.Item] = []
        for section in sections {
            for id in section.exerciseIds {
                let format = formats[id]
                let records = (answers[id] ?? []).map { a in
                    Responses.AnswerRecord(
                        attemptId: a.attemptId, turnId: a.attempt.turnId, outcome: a.attempt.outcome.rawValue,
                        mode: a.attempt.mode.rawValue, response: a.attempt.response, latencyMs: a.attempt.latencyMs,
                        recording: a.recording == nil ? nil : Self.speakingPath(id, attemptId: a.attemptId))
                }
                let writes = format == .writing && answers[id]?.last?.attempt.response != nil
                let score = scores[id] ?? 1
                items.append(
                    .init(
                        exerciseId: id.rawValue, section: section.id, format: format?.rawValue ?? "unknown",
                        score: score, earned: CheckScoring.earned(score: score, answer: checkAnswers[id]),
                        answers: records, writingFile: writes ? Self.writingPath(id) : nil))
            }
        }
        let titles = Dictionary(sections.map { ($0.id, $0.title) }, uniquingKeysWith: { a, _ in a })
        responses = Responses(
            schema: 1, kind: "final-check", installId: installId,
            takenAt: Self.isoText(ms: takenAt, tzOffsetMinutes: tzOffsetMinutes),
            app: .init(version: appVersion, pack: packVersion), indicativePass: result.indicativePass,
            passMarkPerSection: passMarkPerSection,
            sections: result.sections.map {
                .init(
                    id: $0.id, title: titles[$0.id] ?? $0.id.capitalized, points: $0.points, max: $0.max,
                    passed: $0.passed, excluded: $0.excluded)
            },
            items: items)
    }

    /// `final-check-<installId>-<YYYY-MM-DD>-<HHMM>.zip`: the date and time the check was taken, in the learner's
    /// time zone, so every sitting has its own name (two sittings can't end in the same minute); without an install
    /// ID (the device hasn't joined the study), `final-check-<YYYY-MM-DD>-<HHMM>.zip`.
    var fileName: String {
        let text = responses.takenAt  // 2026-10-06T09:30:00+02:00
        let stamp = "\(text.prefix(10))-\(text.dropFirst(11).prefix(2))\(text.dropFirst(14).prefix(2))"
        if let id = responses.installId, !id.isEmpty {
            return "final-check-\(SpeakingRecordings.safe(id))-\(stamp).zip"
        }
        return "final-check-\(stamp).zip"
    }

    static func writingPath(_ id: ExerciseID) -> String { "writing/\(SpeakingRecordings.safe(id.rawValue)).txt" }

    static func speakingPath(_ id: ExerciseID, attemptId: String) -> String {
        "speaking/" + SpeakingRecordings.fileName(exercise: id, attemptID: attemptId)
    }

    /// The archive's files, in order: README.txt, responses.json, writing/…, speaking/…, with the recordings read
    /// from `recordings` (the sitting's folder). A recording that can't be read is left out, and its answer then
    /// names no recording.
    func entries(recordings directory: URL) throws -> [StoredZip.Entry] {
        var out = responses
        var writing: [StoredZip.Entry] = []
        var speaking: [StoredZip.Entry] = []
        for (i, item) in out.items.enumerated() {
            let id = ExerciseID(item.exerciseId)
            for (j, answer) in item.answers.enumerated() where answer.recording != nil {
                let file = directory.appendingPathComponent(
                    SpeakingRecordings.fileName(exercise: id, attemptID: answer.attemptId))
                if let data = try? Data(contentsOf: file) {
                    speaking.append(.init(path: Self.speakingPath(id, attemptId: answer.attemptId), data: data))
                } else {
                    out.items[i].answers[j].recording = nil
                }
            }
            if let path = item.writingFile, let text = item.answers.last?.response {
                writing.append(.init(path: path, data: Data((text + "\n").utf8)))
            }
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        let json = try encoder.encode(out)
        return [
            .init(path: "README.txt", data: Data(Self.readme(out).utf8)),
            .init(path: "responses.json", data: json),
        ] + writing.sorted { $0.path < $1.path } + speaking.sorted { $0.path < $1.path }
    }

    /// The zip's bytes: the entries, dated when the check was taken.
    func archive(recordings directory: URL) throws -> Data {
        try StoredZip.archive(entries(recordings: directory), modified: takenAt, tzOffsetMinutes: tzOffsetMinutes)
    }

    /// `2026-10-08T10:15:00+02:00`
    static func isoText(ms: Int64, tzOffsetMinutes: Int) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = TimeZone(secondsFromGMT: tzOffsetMinutes * 60) ?? TimeZone(secondsFromGMT: 0)
        return f.string(from: Date(timeIntervalSince1970: Double(ms) / 1000))
    }

    var readme: String { Self.readme(responses) }

    static func readme(_ r: Responses) -> String {
        let n = CheckResultContent.number
        let points = r.sections.map { s in
            s.excluded
                ? "- \(s.title): not taken (speaking isn't available on that device)"
                : "- \(s.title): \(n(s.points)) of \(n(s.max))"
        }
        let max = r.sections.first?.max ?? 12
        let installId = r.installId.map { $0.isEmpty ? "none" : $0 } ?? "none (this device hasn't joined the study)"
        return """
            Italiano: final A1 check, for an examiner

            This archive holds one learner's answers to the practice final A1 check in the Italiano app: five \
            sections modelled on CILS A1 (listening, reading, structures, writing and speaking), \(n(max)) points \
            each. The app scores every item automatically; the writing and speaking are here for an examiner to \
            rate. This is a practice check, not an official certificate.

            Install ID: \(installId)
            Taken: \(r.takenAt)
            Course pack: \(r.app.pack)\(r.app.version.map { ", app \($0)" } ?? "")

            Automatic scores (indicative pass: \(n(r.passMarkPerSection)) of \(n(max)) in every section):
            \(points.joined(separator: "\n"))

            Files
            - responses.json: every item with the learner's answers (typed text, chosen option or speech \
            transcript), its automatic score and the section totals.
            - writing/<exercise>.txt: the learner's text for each writing task.
            - speaking/<exercise>-<attempt>.m4a: the recordings of the speaking section, one per spoken answer (a \
            conversation has one per turn). The attempt ID links each recording to its answer in responses.json.

            """
    }
}
