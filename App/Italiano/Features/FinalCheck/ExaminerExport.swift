import Foundation
import LearningCore

/// The examiner export of a final A1 check (docs/12 § Final check export): `final-check-<installId>-<date>.zip`
/// holding exactly
///
/// - `responses.json`: every item with the learner's answers, its automatic score, and the section totals;
/// - `writing/<exerciseId>.txt`: the text of each writing task;
/// - `speaking/<exerciseId>-<attemptId>.m4a`: the speaking section's recordings, one per spoken answer (a
///   conversation has one per turn);
/// - `README.txt`: what the archive is, and the install ID.
///
/// Built from the sitting's own `attempt` events, so the archive says exactly what the event log says. No name,
/// country or other profile data goes in. Platform-neutral and tested; the view hands the zip to the share sheet.
struct ExaminerExport: Sendable {
    struct Section: Sendable, Equatable {
        let id: String
        let title: String
        let exerciseIds: [ExerciseID]
    }

    /// One recorded answer: an `attempt` event of the sitting, and its recording if it was spoken.
    struct Answer: Sendable, Equatable {
        let attemptId: String
        let attempt: AttemptPayload
        let recording: URL?
    }

    let installId: String?
    /// When the check was completed, and the learner's UTC offset then.
    let takenAt: Int64
    let tzOffsetMinutes: Int
    let packVersion: String
    let appVersion: String?
    let sections: [Section]
    let result: FinalCheckResult
    /// Per exercise: its format and its score (points in the check, default 1).
    let formats: [ExerciseID: ExerciseFormat]
    let scores: [ExerciseID: Double]
    /// What the check scored for each exercise (the check recorder's answers).
    let checkAnswers: [ExerciseID: CheckAnswer]
    /// The sitting's attempts per exercise, in the order they were made.
    let answers: [ExerciseID: [Answer]]

    /// `final-check-<installId>-<YYYY-MM-DD>.zip` (the calendar date the check was taken, in the learner's time
    /// zone); without an install ID (the device hasn't joined the study), `final-check-<YYYY-MM-DD>.zip`.
    var fileName: String {
        let day = String(takenAtText.prefix(10))
        if let installId, !installId.isEmpty { return "final-check-\(SpeakingRecordings.safe(installId))-\(day).zip" }
        return "final-check-\(day).zip"
    }

    static func writingPath(_ id: ExerciseID) -> String { "writing/\(SpeakingRecordings.safe(id.rawValue)).txt" }

    static func speakingPath(_ id: ExerciseID, attemptId: String) -> String {
        "speaking/" + SpeakingRecordings.fileName(exercise: id, attemptID: attemptId)
    }

    // MARK: responses.json

    struct Responses: Codable, Equatable {
        struct App: Codable, Equatable {
            let version: String?
            let pack: String
        }

        struct SectionTotal: Codable, Equatable {
            let id: String
            let title: String
            let points: Double
            let max: Double
            let passed: Bool
            /// The device couldn't take it (speaking without speech recognition); not scored.
            let excluded: Bool
        }

        struct Item: Codable, Equatable {
            let exerciseId: String
            let section: String
            let format: String
            let score: Double
            let earned: Double
            let answers: [AnswerRecord]
            /// `writing/<exerciseId>.txt` for writing tasks.
            let writingFile: String?
        }

        struct AnswerRecord: Codable, Equatable {
            let attemptId: String
            let turnId: String?
            let outcome: String
            let mode: String
            /// The typed text, the chosen option, or the speech transcript.
            let response: String?
            let latencyMs: Int
            /// `speaking/<exerciseId>-<attemptId>.m4a` for spoken answers.
            let recording: String?
        }

        let schema: Int
        let kind: String
        let installId: String?
        let takenAt: String
        let app: App
        let indicativePass: Bool
        let passMarkPerSection: Double
        let sections: [SectionTotal]
        let items: [Item]
    }

    /// The archive's files, in order: README.txt, responses.json, writing/…, speaking/…. Recordings that can't be
    /// read are left out (and their answers name no recording).
    func entries(passMarkPerSection: Double = 7) throws -> [StoredZip.Entry] {
        var writing: [StoredZip.Entry] = []
        var speaking: [StoredZip.Entry] = []
        var items: [Responses.Item] = []
        for section in sections {
            for id in section.exerciseIds {
                let format = formats[id]
                var records: [Responses.AnswerRecord] = []
                for a in answers[id] ?? [] {
                    var recordingPath: String?
                    if let url = a.recording, let data = try? Data(contentsOf: url) {
                        let path = Self.speakingPath(id, attemptId: a.attemptId)
                        speaking.append(.init(path: path, data: data))
                        recordingPath = path
                    }
                    records.append(
                        .init(
                            attemptId: a.attemptId, turnId: a.attempt.turnId, outcome: a.attempt.outcome.rawValue,
                            mode: a.attempt.mode.rawValue, response: a.attempt.response,
                            latencyMs: a.attempt.latencyMs, recording: recordingPath))
                }
                var writingFile: String?
                if format == .writing, let text = answers[id]?.last?.attempt.response {
                    let path = Self.writingPath(id)
                    writing.append(.init(path: path, data: Data((text + "\n").utf8)))
                    writingFile = path
                }
                let score = scores[id] ?? 1
                items.append(
                    .init(
                        exerciseId: id.rawValue, section: section.id, format: format?.rawValue ?? "unknown",
                        score: score, earned: CheckScoring.earned(score: score, answer: checkAnswers[id]),
                        answers: records, writingFile: writingFile))
            }
        }
        let titles = Dictionary(sections.map { ($0.id, $0.title) }, uniquingKeysWith: { a, _ in a })
        let responses = Responses(
            schema: 1, kind: "final-check", installId: installId, takenAt: takenAtText,
            app: .init(version: appVersion, pack: packVersion), indicativePass: result.indicativePass,
            passMarkPerSection: passMarkPerSection,
            sections: result.sections.map {
                .init(
                    id: $0.id, title: titles[$0.id] ?? $0.id.capitalized, points: $0.points, max: $0.max,
                    passed: $0.passed, excluded: $0.excluded)
            },
            items: items)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        let json = try encoder.encode(responses)
        return [
            .init(path: "README.txt", data: Data(readme.utf8)),
            .init(path: "responses.json", data: json),
        ] + writing.sorted { $0.path < $1.path } + speaking.sorted { $0.path < $1.path }
    }

    /// `2026-10-08T10:15:00+02:00`
    var takenAtText: String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = TimeZone(secondsFromGMT: tzOffsetMinutes * 60) ?? TimeZone(secondsFromGMT: 0)
        return f.string(from: Date(timeIntervalSince1970: Double(takenAt) / 1000))
    }

    var readme: String {
        let points = result.sections.map { s in
            let title = sections.first { $0.id == s.id }?.title ?? s.id.capitalized
            return s.excluded
                ? "- \(title): not taken (speaking isn't available on that device)"
                : "- \(title): \(CheckResultContent.number(s.points)) of \(CheckResultContent.number(s.max))"
        }
        return """
            Italiano: final A1 check, for an examiner

            This archive holds one learner's answers to the practice final A1 check in the Italiano app: five \
            sections modelled on CILS A1 (listening, reading, structures, writing and speaking), 12 points each. \
            The app scores every item automatically; the writing and speaking are here for an examiner to rate. \
            This is a practice check, not an official certificate.

            Install ID: \(installId.map { $0.isEmpty ? "none" : $0 } ?? "none (this device hasn't joined the study)")
            Taken: \(takenAtText)
            Course pack: \(packVersion)\(appVersion.map { ", app \($0)" } ?? "")

            Automatic scores (indicative pass: 7 of 12 in every section):
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
