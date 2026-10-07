import Foundation

/// The first introduction of a pair (`introductions` table): the first one wins.
public struct Introduction: Codable, Hashable, Sendable {
    public var at: Int64
    public var via: IntroductionVia

    public init(at: Int64, via: IntroductionVia) {
        self.at = at
        self.via = via
    }
}

/// `step_progress`: start and completion times and the derived resume cursor (docs/05 § Replay).
public struct StepProgress: Codable, Hashable, Sendable {
    /// The first `stepStarted`.
    public var startedAt: Int64?
    /// The first `stepCompleted`; a step is complete once it has one.
    public var completedAt: Int64?
    /// Exercises, in presentation order, with a final attempt since the open `stepStarted` (the length of the
    /// answered prefix, so resuming lands on the next unanswered exercise). 0 when no start is open.
    public var cursor: Int
    /// The open `stepStarted` (the last one, which no `stepCompleted` follows), if any.
    public var openStartedAt: Int64?
    /// Exercises with a final attempt since the open start.
    public var finalExercises: Set<ExerciseID>

    public init(startedAt: Int64? = nil, completedAt: Int64? = nil, cursor: Int = 0, openStartedAt: Int64? = nil,
                finalExercises: Set<ExerciseID> = [])
    {
        self.startedAt = startedAt
        self.completedAt = completedAt
        self.cursor = cursor
        self.openStartedAt = openStartedAt
        self.finalExercises = finalExercises
    }

    public var isComplete: Bool { completedAt != nil }
    public var isOpen: Bool { openStartedAt != nil }

    enum CodingKeys: String, CodingKey { case startedAt, completedAt, cursor, openStartedAt, finalExercises }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        startedAt = try c.decodeIfPresent(Int64.self, forKey: .startedAt)
        completedAt = try c.decodeIfPresent(Int64.self, forKey: .completedAt)
        cursor = try c.decode(Int.self, forKey: .cursor)
        openStartedAt = try c.decodeIfPresent(Int64.self, forKey: .openStartedAt)
        finalExercises = Set(try c.decode([ExerciseID].self, forKey: .finalExercises))
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(startedAt, forKey: .startedAt)
        try c.encodeIfPresent(completedAt, forKey: .completedAt)
        try c.encode(cursor, forKey: .cursor)
        try c.encodeIfPresent(openStartedAt, forKey: .openStartedAt)
        try c.encode(finalExercises.sorted(), forKey: .finalExercises)
    }
}

/// Unit states (docs/05 § Unit progression).
public enum UnitState: String, Codable, Sendable {
    case locked, available
    case inProgress = "in_progress"
    case completed, skipped
}

/// `unit_progress` plus the facts its state is derived from.
public struct UnitProgress: Codable, Hashable, Sendable {
    public var state: UnitState
    /// The first `stepStarted` of one of its steps.
    public var startedAt: Int64?
    /// Best overall check score across attempts.
    public var checkScore: Double?
    /// True once any check attempt passed.
    public var checkPassed: Bool?
    /// The first completed check.
    public var completedAt: Int64?
    /// Skipped by placement (the latest `placementCompleted`).
    public var skipped: Bool

    public init(state: UnitState = .locked, startedAt: Int64? = nil, checkScore: Double? = nil,
                checkPassed: Bool? = nil, completedAt: Int64? = nil, skipped: Bool = false)
    {
        self.state = state
        self.startedAt = startedAt
        self.checkScore = checkScore
        self.checkPassed = checkPassed
        self.completedAt = completedAt
        self.skipped = skipped
    }
}

/// `exercise_history`, plus the last outcome (focus items after a failed check) and context.
public struct ExerciseHistory: Codable, Hashable, Sendable {
    public var lastAt: Int64
    /// Attempt events (conversation turns each count).
    public var attempts: Int
    /// First attempts answered `correct` or `correctWithNote`.
    public var firstTryCorrect: Int
    public var lastOutcome: AttemptOutcome
    public var lastContext: AttemptContext

    public init(lastAt: Int64, attempts: Int, firstTryCorrect: Int, lastOutcome: AttemptOutcome,
                lastContext: AttemptContext)
    {
        self.lastAt = lastAt
        self.attempts = attempts
        self.firstTryCorrect = firstTryCorrect
        self.lastOutcome = lastOutcome
        self.lastContext = lastContext
    }
}

/// `focus_items`: reviewed first until `until` (docs/05 § Unit check scoring).
public struct FocusItem: Codable, Hashable, Sendable {
    public var reason: String
    public var until: Int64

    public init(reason: String, until: Int64) {
        self.reason = reason
        self.until = until
    }
}

/// `daily_activity` for one local day (04:00 rollover in each event's own UTC offset).
public struct DailyActivity: Codable, Hashable, Sendable {
    /// Days since 1970-01-01 (`LocalDay.dayNumber`).
    public var day: Int64
    public var activeSeconds: Int
    public var stepsCompleted: Int
    /// First attempts in review sessions.
    public var cardsReviewed: Int

    public init(day: Int64, activeSeconds: Int = 0, stepsCompleted: Int = 0, cardsReviewed: Int = 0) {
        self.day = day
        self.activeSeconds = activeSeconds
        self.stepsCompleted = stepsCompleted
        self.cardsReviewed = cardsReviewed
    }

    /// `YYYY-MM-DD` (the `local_day` column).
    public var localDay: String { LocalDay.string(dayNumber: day) }

    /// docs/05 § The Today planner: a day counts with ≥ 1 completed step or ≥ 5 reviewed cards.
    public var isActive: Bool { stepsCompleted >= 1 || cardsReviewed >= 5 }
}

/// The best result of a check across attempts (the final A1 check).
public struct CheckRecord: Codable, Hashable, Sendable {
    public var bestScore: Double
    public var passed: Bool
    public var firstCompletedAt: Int64
    public var attempts: Int

    public init(bestScore: Double, passed: Bool, firstCompletedAt: Int64, attempts: Int) {
        self.bestScore = bestScore
        self.passed = passed
        self.firstCompletedAt = firstCompletedAt
        self.attempts = attempts
    }
}

/// The latest `placementCompleted`.
public struct PlacementRecord: Codable, Hashable, Sendable {
    public var startUnit: UnitID
    public var at: Int64

    public init(startUnit: UnitID, at: Int64) {
        self.startUnit = startUnit
        self.at = at
    }
}

/// Everything derived from the event log and the pack (docs/05 § Replay). Built only by `Replay`; equal event
/// sets give equal states on every device, and `canonicalEncoding()` is byte-stable for comparing them.
public struct LearnerState: Equatable, Sendable {
    /// FSRS memory per (item, skill).
    public internal(set) var memory: [ItemSkillPair: MemoryState] = [:]
    public internal(set) var introductions: [ItemSkillPair: Introduction] = [:]
    public internal(set) var steps: [StepID: StepProgress] = [:]
    /// One row per unit of the pack (see `Replay.initialState(content:)`).
    public internal(set) var units: [UnitID: UnitProgress] = [:]
    /// Can-dos reached, with the first time (union over check attempts).
    public internal(set) var canDos: [CanDoID: Int64] = [:]
    /// Keyed by exercise ID, including generated `gen:` cards.
    public internal(set) var exerciseHistory: [ExerciseID: ExerciseHistory] = [:]
    public internal(set) var focusItems: [ItemSkillPair: FocusItem] = [:]
    public internal(set) var dailyActivity: [Int64: DailyActivity] = [:]
    public internal(set) var finalCheck: CheckRecord?
    public internal(set) var placement: PlacementRecord?
    /// When each format was last used (first attempts) per item, for the card selector's rotation.
    public internal(set) var formatLastUsed: [ItemID: [ExerciseFormat: Int64]] = [:]
    /// Seconds per review card of the most recent review sessions (median → the Today estimate).
    public internal(set) var secondsPerCardSamples: [Double] = []
    /// Review cards answered per review session whose `session` event hasn't been applied yet.
    public internal(set) var openReviewSessions: [String: Int] = [:]
    /// Per local day: placement-introduced scheduled pairs that got their first memory in a review session (new
    /// catch-up cards, capped at 15 a day).
    public internal(set) var catchUpStarted: [Int64: Int] = [:]
    /// The last event applied, in `(at, id)` order.
    public internal(set) var lastApplied: EventKey?

    public init() {}

    // MARK: Queries

    public func isIntroduced(_ pair: ItemSkillPair) -> Bool { introductions[pair] != nil }

    public func unitState(_ unit: UnitID) -> UnitState { units[unit]?.state ?? .locked }

    public func stepProgress(_ step: StepID) -> StepProgress? { steps[step] }

    /// The derived resume cursor of a step (0 when it has no open start).
    public func cursor(_ step: StepID) -> Int { steps[step]?.cursor ?? 0 }

    public func isStepComplete(_ step: StepID) -> Bool { steps[step]?.completedAt != nil }

    public func activity(day: Int64) -> DailyActivity { dailyActivity[day] ?? DailyActivity(day: day) }

    /// Focus pairs still active at `now`, sorted.
    public func activeFocus(now: Int64) -> [ItemSkillPair] {
        focusItems.filter { $0.value.until > now }.map(\.key).sorted()
    }

    // MARK: Canonical encoding

    /// Byte-stable JSON of the whole state: every collection as an array sorted by key, object keys sorted.
    public func canonicalEncoding() throws -> Data {
        try EventCodec.makeEncoder().encode(self)
    }
}

extension LearnerState: Codable {
    struct MemoryRow: Codable { var itemId: ItemID; var skill: Skill; var state: MemoryState }
    struct IntroductionRow: Codable { var itemId: ItemID; var skill: Skill; var at: Int64; var via: IntroductionVia }
    struct StepRow: Codable { var stepId: StepID; var progress: StepProgress }
    struct UnitRow: Codable { var unitId: UnitID; var progress: UnitProgress }
    struct CanDoRow: Codable { var canDoId: CanDoID; var reachedAt: Int64 }
    struct ExerciseRow: Codable { var exerciseId: ExerciseID; var history: ExerciseHistory }
    struct FocusRow: Codable { var itemId: ItemID; var skill: Skill; var reason: String; var until: Int64 }
    struct FormatRow: Codable { var itemId: ItemID; var format: ExerciseFormat; var at: Int64 }
    struct SessionRow: Codable { var sessionId: String; var cards: Int }
    struct DayCount: Codable { var day: Int64; var count: Int }

    enum CodingKeys: String, CodingKey {
        case memory, introductions, steps, units, canDos, exerciseHistory, focusItems, dailyActivity, finalCheck
        case placement, formatLastUsed, secondsPerCardSamples, openReviewSessions, catchUpStarted, lastApplied
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(memory.sorted { $0.key < $1.key }.map {
            MemoryRow(itemId: $0.key.itemId, skill: $0.key.skill, state: $0.value)
        }, forKey: .memory)
        try c.encode(introductions.sorted { $0.key < $1.key }.map {
            IntroductionRow(itemId: $0.key.itemId, skill: $0.key.skill, at: $0.value.at, via: $0.value.via)
        }, forKey: .introductions)
        try c.encode(steps.sorted { $0.key < $1.key }.map { StepRow(stepId: $0.key, progress: $0.value) },
                     forKey: .steps)
        try c.encode(units.sorted { $0.key < $1.key }.map { UnitRow(unitId: $0.key, progress: $0.value) },
                     forKey: .units)
        try c.encode(canDos.sorted { $0.key < $1.key }.map { CanDoRow(canDoId: $0.key, reachedAt: $0.value) },
                     forKey: .canDos)
        try c.encode(exerciseHistory.sorted { $0.key < $1.key }.map {
            ExerciseRow(exerciseId: $0.key, history: $0.value)
        }, forKey: .exerciseHistory)
        try c.encode(focusItems.sorted { $0.key < $1.key }.map {
            FocusRow(itemId: $0.key.itemId, skill: $0.key.skill, reason: $0.value.reason, until: $0.value.until)
        }, forKey: .focusItems)
        try c.encode(dailyActivity.sorted { $0.key < $1.key }.map(\.value), forKey: .dailyActivity)
        try c.encodeIfPresent(finalCheck, forKey: .finalCheck)
        try c.encodeIfPresent(placement, forKey: .placement)
        var formats: [FormatRow] = []
        for (item, byFormat) in formatLastUsed.sorted(by: { $0.key < $1.key }) {
            for (format, at) in byFormat.sorted(by: { $0.key.rawValue < $1.key.rawValue }) {
                formats.append(FormatRow(itemId: item, format: format, at: at))
            }
        }
        try c.encode(formats, forKey: .formatLastUsed)
        try c.encode(secondsPerCardSamples, forKey: .secondsPerCardSamples)
        try c.encode(openReviewSessions.sorted { $0.key < $1.key }.map {
            SessionRow(sessionId: $0.key, cards: $0.value)
        }, forKey: .openReviewSessions)
        try c.encode(catchUpStarted.sorted { $0.key < $1.key }.map { DayCount(day: $0.key, count: $0.value) },
                     forKey: .catchUpStarted)
        try c.encodeIfPresent(lastApplied, forKey: .lastApplied)
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        for row in try c.decode([MemoryRow].self, forKey: .memory) {
            memory[ItemSkillPair(row.itemId, row.skill)] = row.state
        }
        for row in try c.decode([IntroductionRow].self, forKey: .introductions) {
            introductions[ItemSkillPair(row.itemId, row.skill)] = Introduction(at: row.at, via: row.via)
        }
        for row in try c.decode([StepRow].self, forKey: .steps) { steps[row.stepId] = row.progress }
        for row in try c.decode([UnitRow].self, forKey: .units) { units[row.unitId] = row.progress }
        for row in try c.decode([CanDoRow].self, forKey: .canDos) { canDos[row.canDoId] = row.reachedAt }
        for row in try c.decode([ExerciseRow].self, forKey: .exerciseHistory) {
            exerciseHistory[row.exerciseId] = row.history
        }
        for row in try c.decode([FocusRow].self, forKey: .focusItems) {
            focusItems[ItemSkillPair(row.itemId, row.skill)] = FocusItem(reason: row.reason, until: row.until)
        }
        for day in try c.decode([DailyActivity].self, forKey: .dailyActivity) { dailyActivity[day.day] = day }
        finalCheck = try c.decodeIfPresent(CheckRecord.self, forKey: .finalCheck)
        placement = try c.decodeIfPresent(PlacementRecord.self, forKey: .placement)
        for row in try c.decode([FormatRow].self, forKey: .formatLastUsed) {
            formatLastUsed[row.itemId, default: [:]][row.format] = row.at
        }
        secondsPerCardSamples = try c.decode([Double].self, forKey: .secondsPerCardSamples)
        for row in try c.decode([SessionRow].self, forKey: .openReviewSessions) {
            openReviewSessions[row.sessionId] = row.cards
        }
        for row in try c.decode([DayCount].self, forKey: .catchUpStarted) { catchUpStarted[row.day] = row.count }
        lastApplied = try c.decodeIfPresent(EventKey.self, forKey: .lastApplied)
    }
}
