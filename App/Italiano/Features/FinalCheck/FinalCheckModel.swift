import Foundation
import LearningCore
import Observation

// The final A1 check (docs/05 § Final A1 check, docs/06 §20): five sections modelled on CILS A1 with check-mode
// rules (one attempt per item, no hints, no feedback until the end), speaking always recorded, a result with an
// indicative pass of 7/12 per section, and the examiner export. The engine scores (`CheckScoring.scoreFinal`); this
// plays the items through the same exercise models as lessons. Platform-neutral and tested.

@MainActor
@Observable
final class FinalCheckSessionModel {
    enum Phase: Sendable, Equatable { case intro, playing, finished }

    struct Section: Sendable, Equatable {
        let id: String
        let title: String
        let exerciseIds: [ExerciseID]
    }

    /// Every section, as the pack lists them.
    let sections: [Section]
    /// Sections this device can't take (speaking without speech recognition): left out of the sitting, flagged
    /// on the result.
    let excluded: Set<String>
    private(set) var phase: Phase = .intro
    private(set) var index = 0
    private(set) var host: ExerciseHostModel?
    private(set) var payload: ExercisePayload?
    /// The items of the sections taken, in order, with their section.
    @ObservationIgnored let order: [(section: Section, exercise: ExerciseID)]
    @ObservationIgnored let bundle: LessonBundle
    @ObservationIgnored let recorder = CheckRecorder()
    @ObservationIgnored let log: FinalCheckLog
    @ObservationIgnored private let env: ExerciseEnvironment
    /// The event sink (context `final`). Exercise models hold their sink weakly; this model is the sink they see.
    @ObservationIgnored private let inner: (any AttemptSink)?

    init(
        sections: [Section], excluded: Set<String>, bundle: LessonBundle, env: ExerciseEnvironment,
        sink: (any AttemptSink)?, log: FinalCheckLog
    ) {
        self.sections = sections
        self.excluded = excluded
        self.bundle = bundle
        self.env = env
        inner = sink
        self.log = log
        order = sections.filter { !excluded.contains($0.id) }.flatMap { s in s.exerciseIds.map { (s, $0) } }
    }

    /// The intro's Start.
    func start() {
        guard phase == .intro else { return }
        phase = .playing
        makeHost()
    }

    /// Continue after an item (unanswered items earn nothing).
    func advance() {
        guard phase == .playing else { return }
        index += 1
        makeHost()
    }

    var currentExercise: ExerciseID? { phase == .playing && index < order.count ? order[index].exercise : nil }
    var currentSection: Section? { phase == .playing && index < order.count ? order[index].section : nil }
    var progress: Double { order.isEmpty || phase == .finished ? 1 : Double(index) / Double(order.count) }
    /// "12 / 40"
    var counter: String { "\(min(index + 1, order.count)) / \(order.count)" }

    /// Where the recogniser keeps the current spoken answer (the speaking section always records, docs/09).
    func recordingDestination() -> URL? {
        currentExercise.flatMap { log.recordings?.destination(for: $0) }
    }

    private func makeHost() {
        while index < order.count {
            let id = order[index].exercise
            if let p = bundle.exercises[id], let h = ExerciseHostModel.make(p, env: env, sink: self) {
                host = h
                payload = p
                return
            }
            index += 1  // a payload the app can't play is passed over (it earns nothing)
        }
        host = nil
        payload = nil
        phase = .finished
    }
}

extension FinalCheckSessionModel: AttemptSink {
    /// Every graded answer: the check recorder keeps what it scores, the event log gets the `attempt`.
    func record(_ draft: AttemptDraft) {
        recorder.record(draft)
        inner?.record(draft)
    }
}

/// The sitting's `attempt` events as they are written, each spoken answer with its recording: what the examiner
/// export is built from.
@MainActor
final class FinalCheckLog {
    let recordings: SpeakingRecordings?
    private(set) var answers: [ExerciseID: [ExaminerExport.Answer]] = [:]

    init(recordings: SpeakingRecordings?) { self.recordings = recordings }

    /// The event sink's write: attempts are kept, and a pending recording of the same exercise takes the event's ID.
    func append(_ event: Event) {
        guard case .attempt(let a) = event.payload else { return }
        let recording = a.mode == .spoken ? recordings?.attach(attemptID: event.id, exercise: a.exerciseId) : nil
        answers[a.exerciseId, default: []].append(.init(attemptId: event.id, attempt: a, recording: recording))
    }

    var recordingURLs: [URL] { answers.values.flatMap { $0.compactMap(\.recording) }.sorted { $0.path < $1.path } }
}

/// The final check's words (docs/06 §20, docs/07 § Copy).
enum FinalCheckCopy {
    static let title = "Final A1 check"
    static let introBody =
        "Five sections modelled on the CILS A1 exam: listening, reading, structures, writing and speaking, 12 points "
        + "each. It takes about 45 minutes."
    static let introRules =
        "One try per question, no hints and no feedback until the end. Your spoken answers are recorded so an "
        + "examiner can listen to them; the recordings stay on this device."
    static let noSpeech = "Speaking isn't available on this device, so the speaking section is left out."
    static let disclaimer = "This is a practice check, not an official certificate."
    static let passRule = "Indicative pass: 7 of 12 in every section."
    static let exportLine =
        "Your answers, writing and recordings in one file for an examiner. Nothing is uploaded: you choose where "
        + "to send it."
    static let exportFailed = "The export couldn't be saved on this device."
}

/// The final check's result screen (docs/06 §20): per-section scores out of 12, the indicative pass, the line that
/// it isn't a certificate.
struct FinalCheckResultContent: Sendable, Equatable {
    struct Section: Sendable, Equatable {
        let title: String
        /// "8 of 12", "6.5 of 12", or "Not taken" for an excluded section
        let score: String
        let fraction: Double
        let passed: Bool
        let excluded: Bool
    }

    let indicativePass: Bool
    let headline: String
    let sections: [Section]

    init(result: FinalCheckResult, titles: [String: String]) {
        indicativePass = result.indicativePass
        headline =
            result.indicativePass
            ? "You reached the indicative A1 pass in every section."
            : "Not every section reached 7 of 12 yet."
        sections = result.sections.map { s in
            Section(
                title: titles[s.id] ?? s.id.capitalized,
                score: s.excluded
                    ? "Not taken"
                    : "\(CheckResultContent.number(s.points)) of \(CheckResultContent.number(s.max))",
                fraction: s.max > 0 ? s.points / s.max : 0, passed: s.passed, excluded: s.excluded)
        }
    }
}
