import Foundation
import GRDB
import LearningCore
import LearningCoreTestSupport
import Testing

@testable import Storage

/// 2026-01-05T09:00:00Z, a Monday.
let mondayNine: Int64 = 1_767_603_600_000

/// A learner database in its own temporary folder (removed when the test process's work folder is cleaned).
struct TestLearnerDB {
    let folder: URL
    let url: URL
    let clock: FixedClock

    init(_ name: String = #function, start: Int64 = mondayNine) throws {
        let slug = name.filter { $0.isLetter || $0.isNumber }
        folder = TestPack.workDirectory.appendingPathComponent("learner-\(slug)-\(UUID().uuidString.prefix(8))")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        url = folder.appendingPathComponent(LearnerStore.fileName)
        clock = FixedClock(ms: start)
    }

    func open(
        content: ContentIndex = TestCourse.standard, device: String = "store-device",
        checkpointInterval: Int = 250
    ) throws -> LearnerStore {
        try LearnerStore(
            url: url, content: content, clock: clock, ids: SeededUUIDSource(seed: device),
            options: .init(checkpointInterval: checkpointInterval))
    }

    /// A second connection to the same file, for looking at rows and for injecting failures.
    func queue() throws -> DatabaseQueue { try DatabaseQueue(path: url.path) }
}

/// Every derived table's rows, sorted, as strings: equal snapshots mean equal tables.
func derivedSnapshot(_ store: LearnerStore) throws -> [String: [String]] {
    try read(store) { db in
        var out: [String: [String]] = [:]
        for table in LearnerSchema.derivedTables + ["derived_meta"] {
            out[table] = try Row.fetchAll(db, sql: "SELECT * FROM \(table)").map { $0.description }.sorted()
        }
        return out
    }
}

func count(_ store: LearnerStore, _ table: String) throws -> Int {
    try read(store) { db in try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM \(table)") ?? 0 }
}

/// A deterministic learner on `TestCourse`: lesson steps in course order (start, introductions, every exercise in
/// presentation order with mixed outcomes and some second attempts, completion), review sessions over introduced
/// pairs, glosses and audio, one session event per activity, a check per unit; a day per round. Realistic enough
/// for replay timing: about seven in ten events are attempts.
struct SyntheticLearner {
    let content: ContentIndex
    let clock: FixedClock
    let factory: EventFactory
    var rng: SplitMix64
    var events: [Event] = []
    var introduced: [ItemSkillPair] = []
    var seen = Set<ItemSkillPair>()

    init(
        content: ContentIndex = TestCourse.standard, device: String = "synthetic", start: Int64 = mondayNine,
        tz: Int = 60
    ) {
        self.content = content
        clock = FixedClock(ms: start, tzOffsetMinutes: tz)
        factory = EventFactory(
            deviceId: device, packVersion: content.packVersion, clock: clock,
            ids: SeededUUIDSource(seed: device))
        rng = SplitMix64(seedString: device)
    }

    /// The first `count` events of the simulated learner.
    static func log(
        _ count: Int, content: ContentIndex = TestCourse.standard, device: String = "synthetic"
    )
        -> [Event]
    {
        var learner = SyntheticLearner(content: content, device: device)
        learner.run(until: count)
        return Array(learner.events.prefix(count))
    }

    mutating func record(_ event: Event?) {
        guard let event else { return }
        events.append(event)
        clock.advance(byMs: 4_000)
    }

    mutating func outcome() -> AttemptOutcome {
        switch rng.nextInt(below: 10) {
        case 0: .wrong
        case 1: .almost
        case 2: .correctWithNote
        default: .correct
        }
    }

    mutating func run(until count: Int) {
        let steps = content.steps.filter { $0.kind != .check && $0.kind != .fluency }
        var stepIndex = 0
        var day = 0
        while events.count < count {
            let lesson = "lesson-\(day)"
            let started = clock.nowMs()
            for _ in 0..<3 {
                runStep(steps[stepIndex % steps.count], session: lesson)
                stepIndex += 1
            }
            record(
                factory.session(
                    sessionId: lesson, kind: .lesson, platform: .iPhone, startedAt: started,
                    endedAt: clock.nowMs(), activeSeconds: Int((clock.nowMs() - started) / 1000)))
            review(session: "review-\(day)", cards: 25)
            if stepIndex % steps.count < 3 { completeCheck(unit: content.units[day % content.units.count].id) }
            day += 1
            clock.set(ms: mondayNine + Int64(day) * 86_400_000 + Int64(rng.nextInt(below: 3_600_000)))
        }
    }

    mutating func runStep(_ step: ContentIndex.Step, session: String) {
        record(factory.stepStarted(step.id, sessionId: session))
        let fresh = step.introduces.filter { seen.insert($0).inserted }
        introduced += fresh
        let via: IntroductionVia =
            switch step.kind {
            case .story, .listening, .reading: .story
            case .note: .note
            case .sounds: .sounds
            default: .preview
            }
        record(factory.introduced(fresh, via: via, stepId: step.id))
        for text in step.textIds.prefix(1) {
            record(factory.glossTapped(textId: text, line: 1, token: 2, itemId: nil))
            record(
                factory.audioPlayed(
                    audioId: AudioID("a:000000000000"), textId: text, rate: 1, playedMs: 30_000,
                    context: .story))
        }
        for id in step.presentationOrder + step.exerciseIds {
            guard let exercise = content.exercise(id) else { continue }
            let first = outcome()
            answer(exercise, first, context: .lesson, step: step.id, session: session)
            if first == .wrong {
                answer(exercise, .correct, context: .lesson, step: step.id, session: session, index: 2)
            }
        }
        record(factory.stepCompleted(step.id, sessionId: session, durationMs: 120_000))
    }

    mutating func answer(
        _ exercise: ContentIndex.Exercise, _ outcome: AttemptOutcome, context: AttemptContext,
        step: StepID?, session: String, index: Int = 1
    ) {
        let mode: AnswerMode =
            exercise.format.family == .tapped ? .tapped : exercise.format == .repeat ? .spoken : .typed
        record(
            factory.attempt(
                exerciseId: exercise.id, format: exercise.format, context: context, stepId: step,
                sessionId: session, attemptIndex: index, outcome: outcome, targets: exercise.targets,
                response: mode == .typed ? "una risposta" : nil, mode: mode, latencyMs: 3_000,
                feedbackShown: index == 2 ? .hint : .none))
    }

    mutating func review(session: String, cards: Int) {
        guard !introduced.isEmpty else { return }
        let started = clock.nowMs()
        for _ in 0..<cards {
            let pair = introduced[rng.nextInt(below: introduced.count)]
            let format: ExerciseFormat = pair.skill == .read ? .choice : .recall
            record(
                factory.attempt(
                    exerciseId: ExerciseID("gen:\(pair.skill.rawValue):\(pair.itemId.rawValue)"), format: format,
                    context: .review, sessionId: session, outcome: outcome(), targets: [pair],
                    mode: format == .choice ? .tapped : .typed, latencyMs: 2_500))
        }
        record(
            factory.session(
                sessionId: session, kind: .review, platform: .iPhone, startedAt: started,
                endedAt: clock.nowMs(), activeSeconds: Int((clock.nowMs() - started) / 1000)))
    }

    mutating func completeCheck(unit: UnitID) {
        guard let check = content.checks.first(where: { $0.unitId == unit }) else { return }
        let session = "check-\(unit.rawValue)-\(events.count)"
        for id in check.exerciseIds {
            guard let exercise = content.exercise(id) else { continue }
            answer(exercise, outcome(), context: .check, step: check.stepId, session: session)
        }
        let passed = rng.nextInt(below: 4) > 0
        record(
            factory.checkCompleted(
                CheckCompletedPayload(
                    checkId: check.id, kind: .unit,
                    sections: check.sections.map { CheckSectionResult(id: $0.id, earned: passed ? 1 : 0, possible: 1) },
                    overall: passed ? 0.8 : 0.4, passed: passed,
                    canDosReached: passed ? content.canDos.filter { $0.unitId == unit }.map(\.id) : [])))
    }
}

/// A synchronous read on the store's pool (inside async tests GRDB's async overload would win).
func read<T>(_ store: LearnerStore, _ body: (Database) throws -> T) throws -> T { try store.pool.read(body) }
