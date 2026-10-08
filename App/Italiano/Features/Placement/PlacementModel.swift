import Foundation
import LearningCore
import Observation

// Placement (docs/05 § Placement, docs/06 §19): offered after onboarding when the learner says they know some
// Italian. An intro, then the adaptive blocks with one attempt per item, no feedback and a progress bar, then
// "We'll start you at Unit N" with Start there and Start from the beginning (also offered at any point before).
// The engine (`PlacementSession`) decides the blocks and the start unit; this plays the exercises through the same
// models as lessons. Platform-neutral and tested.

@MainActor
@Observable
final class PlacementSessionModel {
    enum Phase: Sendable, Equatable { case intro, playing, result }

    private(set) var phase: Phase = .intro
    private(set) var session: PlacementSession
    private(set) var host: ExerciseHostModel?
    /// The payload behind `host`.
    private(set) var payload: ExercisePayload?
    @ObservationIgnored let content: ContentIndex
    @ObservationIgnored let bundle: LessonBundle
    @ObservationIgnored private let env: ExerciseEnvironment
    /// The event sink (`attempt` events, context `placement`). Exercise models hold their sink weakly; this model
    /// is the sink they see, so it lives as long as the sitting.
    @ObservationIgnored private let inner: (any AttemptSink)?

    init(
        session: PlacementSession, content: ContentIndex, bundle: LessonBundle, env: ExerciseEnvironment,
        sink: (any AttemptSink)?
    ) {
        self.session = session
        self.content = content
        self.bundle = bundle
        self.env = env
        inner = sink
    }

    /// The intro's Start.
    func start() {
        guard phase == .intro else { return }
        phase = .playing
        makeHost()
    }

    /// Continue after an exercise (answered or not: an unanswered item earns nothing).
    func advance() {
        guard phase == .playing else { return }
        session.advance(content: content)
        makeHost()
    }

    var progress: Double { phase == .intro ? 0 : session.progress }

    /// "Unit 2 questions": which block is on screen.
    var blockLine: String? {
        guard let unit = session.currentBlock?.unitId, let ord = content.unitOrd(unit) else { return nil }
        return "Unit \(ord) questions"
    }

    /// The start unit once the blocks are over.
    var startUnit: UnitID? { session.startUnit(content: content) }

    /// "Start there": nil until the blocks are over.
    var completion: PlacementCompletion? { session.completion(content: content) }

    /// "Start from the beginning", at any point.
    var fromBeginning: PlacementCompletion? { session.startFromBeginning(content: content) }

    /// Whether the sitting has begun (a `session` event is written when it ends).
    var hasStarted: Bool { phase != .intro }

    private func makeHost() {
        while let id = session.currentExercise {
            if let p = bundle.exercises[id], let h = ExerciseHostModel.make(p, env: env, sink: self) {
                host = h
                payload = p
                return
            }
            session.advance(content: content)  // a payload the app can't play is passed over
        }
        host = nil
        payload = nil
        phase = .result
    }
}

extension PlacementSessionModel: AttemptSink {
    /// Every graded answer: the engine keeps the item's one attempt, the event log gets the `attempt`.
    func record(_ draft: AttemptDraft) {
        session.record(draft.outcome, for: draft.exerciseID)
        inner?.record(draft)
    }
}

/// The placement screens' words (docs/06 §19, docs/07 § Copy).
enum PlacementCopy {
    static let introTitle = "Let's find your level"
    static let introBody =
        "You'll get five short questions from each unit, starting with Unit 1. When a set gets hard, we stop and "
        + "start you there."
    static let introRules = "No hints and no feedback: just do your best. It takes about ten minutes."
    static let mokaLine = "If you're not sure, have a guess. A wrong answer just means you'll see that unit."
    static let leaveTitle = "Leave the placement?"
    static let leaveMessage = "You can start from Unit 0 instead. Your answers so far won't move you ahead."
}

/// "We'll start you at Unit N: *title*" (docs/06 §19).
struct PlacementResultContent: Sendable, Equatable {
    let startUnit: UnitID
    let headline: String
    let titleIt: String
    let titleEn: String
    /// What happens to the skipped units.
    let detail: String

    init(startUnit: UnitID, content: ContentIndex, outline: CourseOutline) {
        self.startUnit = startUnit
        let number = outline.unit(startUnit)?.number ?? content.unitOrd(startUnit) ?? 0
        headline = "We'll start you at Unit \(number):"
        titleIt = outline.unit(startUnit)?.titleIt ?? startUnit.rawValue
        titleEn = outline.unit(startUnit)?.titleEn ?? ""
        let skipped = content.units.filter { ($0.ord) < (content.unitOrd(startUnit) ?? 0) }
        let numbers = skipped.map { outline.unit($0.id)?.number ?? $0.ord }
        switch numbers.count {
        case 0:
            detail = "You'll start with the first unit."
        case 1:
            detail =
                "Unit \(numbers[0]) is marked as skipped. Its words join your reviews as catch-up cards, up to "
                + "15 a day."
        default:
            detail =
                "Units \(numbers[0]) to \(numbers[numbers.count - 1]) are marked as skipped. Their words join "
                + "your reviews as catch-up cards, up to 15 a day."
        }
    }
}
