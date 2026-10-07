import Foundation

@testable import LearningCore

/// Collects reducer log lines.
final class RecordingLogger: CoreLogger, @unchecked Sendable {
    // @unchecked: `lines` is guarded by `lock`.
    private let lock = NSLock()
    private var storage: [String] = []

    func log(_ message: String) { lock.withLock { storage.append(message) } }
    var lines: [String] { lock.withLock { storage } }
}

/// 2026-01-05T09:00:00Z, a Monday.
let mondayNine: Int64 = 1_767_603_600_000
let minute: Int64 = 60_000
let hour: Int64 = 3_600_000
let day: Int64 = 86_400_000

/// A learner's device in tests: a clock, an event factory, its own event log, and the state replayed in place.
final class TestDevice {
    let content: ContentIndex
    let clock: FixedClock
    let factory: EventFactory
    let platform: Platform
    var events: [Event] = []
    var state: LearnerState

    init(_ deviceId: String = "device-a", content: ContentIndex = TestCourse.standard, start: Int64 = mondayNine,
         tz: Int = 0, platform: Platform = .iPhone)
    {
        self.content = content
        self.clock = FixedClock(ms: start, tzOffsetMinutes: tz)
        self.factory = EventFactory(deviceId: deviceId, packVersion: content.packVersion, clock: clock,
                                    ids: SeededUUIDSource(seed: deviceId))
        self.platform = platform
        self.state = Replay.initialState(content: content)
    }

    var now: Int64 { clock.nowMs() }
    var tz: Int { clock.tzOffsetMinutes() }

    func advance(_ ms: Int64) { clock.advance(byMs: ms) }

    @discardableResult
    func record(_ event: Event?) -> Event? {
        guard let event else { return nil }
        events.append(event)
        Replay.reduce(&state, event, content: content)
        clock.advance(byMs: 1_000)
        return event
    }

    /// Enters a step like the player: `stepStarted` only when no start is open, then the step's introductions and,
    /// if something is still missing, the mini-preview's `catchup` introductions.
    @discardableResult
    func enter(_ stepId: StepID, session: String = "s-lesson") -> StepEntry? {
        guard let step = content.step(stepId) else { return nil }
        if !(state.stepProgress(stepId)?.isOpen ?? false) { record(factory.stepStarted(stepId, sessionId: session)) }
        let entry = Eligibility.enter(step, state: state, content: content)
        if let payload = entry.introducedPayload { record(factory.introduced(payload)) }
        if let payload = entry.catchupPayload { record(factory.introduced(payload)) }
        return entry
    }

    @discardableResult
    func answer(_ exerciseId: ExerciseID, _ outcome: AttemptOutcome, context: AttemptContext = .lesson,
                step: StepID? = nil, session: String = "s-lesson", attemptIndex: Int = 1, mode: AnswerMode? = nil,
                pairOutcomes: [AttemptOutcome]? = nil, turnId: String? = nil, format: ExerciseFormat? = nil,
                targets: [ItemSkillPair]? = nil, response: String? = nil) -> Event?
    {
        let exercise = content.exercise(exerciseId)
        let fmt = format ?? exercise?.format ?? .recall
        let answerMode = mode ?? (fmt.family == .tapped ? .tapped : fmt == .repeat ? .spoken : .typed)
        // Steps run in lesson and check contexts; reviews and placement have no step.
        let stepId = step ?? (context == .lesson || context == .check ? exercise?.stepId : nil)
        return record(factory.attempt(
            exerciseId: exerciseId, turnId: turnId, format: fmt, context: context, stepId: stepId,
            sessionId: session, attemptIndex: attemptIndex, outcome: outcome,
            targets: targets ?? exercise?.targets ?? [],
            pairOutcomes: pairOutcomes, response: response, mode: answerMode, latencyMs: 3_000))
    }

    @discardableResult
    func complete(_ stepId: StepID, session: String = "s-lesson") -> Event? {
        record(factory.stepCompleted(stepId, sessionId: session, durationMs: 60_000))
    }

    /// Runs a whole step answering every exercise in presentation order with `outcome`.
    func run(_ stepId: StepID, outcome: AttemptOutcome = .correct) {
        enter(stepId)
        guard let step = content.step(stepId) else { return }
        for id in step.presentationOrder { answer(id, outcome, step: stepId) }
        complete(stepId)
    }

    /// Runs every step of a unit except the check and fluency, then completes the check with a score.
    func runUnit(_ k: Int, checkPassed: Bool = true) {
        for step in content.steps(in: TestCourse.unitId(k)) where step.kind != .check && step.kind != .fluency {
            run(step.id)
        }
        completeCheck(k, passed: checkPassed)
    }

    func completeCheck(_ k: Int, passed: Bool, overall: Double? = nil, canDos: [CanDoID]? = nil) {
        let stepId = TestCourse.unitStep(k, "check")
        enter(stepId, session: "s-check-\(k)")
        guard let check = content.check(TestCourse.checkId(k)) else { return }
        for id in check.exerciseIds {
            answer(id, passed ? .correct : .wrong, context: .check, step: stepId, session: "s-check-\(k)")
        }
        record(factory.checkCompleted(CheckCompletedPayload(
            checkId: check.id, kind: .unit,
            sections: check.sections.map { CheckSectionResult(id: $0.id, earned: passed ? 1 : 0, possible: 1) },
            overall: overall ?? (passed ? 1 : 0), passed: passed,
            canDosReached: canDos ?? (passed ? [TestCourse.canDo(k, "a"), TestCourse.canDo(k, "b")] : []))))
        complete(stepId, session: "s-check-\(k)")
    }
}

extension LearnerState {
    func canonicalString() throws -> String { String(decoding: try canonicalEncoding(), as: UTF8.self) }
}
