import Foundation

/// Where an event row came from: written on this device, or received through sync (`events.origin`, docs/03).
public enum EventOrigin: String, Codable, Sendable {
    case local, remote
}

/// The event types of docs/05 § Events.
public enum EventType: String, Codable, Sendable, CaseIterable {
    case introduced, attempt, stepStarted, stepCompleted, glossTapped, audioPlayed, session
    case checkCompleted, placementCompleted, onboardingCompleted
}

/// Replay order: `(at, id)` on every device (docs/05 § Events, docs/08 § Merge rules).
public struct EventKey: Hashable, Comparable, Codable, Sendable {
    public var at: Int64
    public var id: String

    public init(at: Int64, id: String) {
        self.at = at
        self.id = id
    }

    public static func < (lhs: Self, rhs: Self) -> Bool {
        lhs.at != rhs.at ? lhs.at < rhs.at : lhs.id.utf8.lexicographicallyPrecedes(rhs.id.utf8)
    }
}

/// One immutable learner event: the envelope of the `events` table (docs/03 § The learner database) and a typed
/// payload. Events are never updated or deleted (CLAUDE.md hard rule 5).
public struct Event: Hashable, Sendable {
    /// The payload schema version every type has at launch.
    public static let currentSchema = 1

    /// Lowercase UUID.
    public var id: String
    /// Milliseconds since the epoch, UTC.
    public var at: Int64
    /// The device's UTC offset when the event happened (local-day maths).
    public var tzOffsetMin: Int
    public var deviceId: String
    public var schema: Int
    public var packVersion: String
    public var payload: EventPayload
    public var origin: EventOrigin

    public init(id: String, at: Int64, tzOffsetMin: Int, deviceId: String, schema: Int = Event.currentSchema,
                packVersion: String, payload: EventPayload, origin: EventOrigin = .local)
    {
        self.id = id.lowercased()
        self.at = at
        self.tzOffsetMin = tzOffsetMin
        self.deviceId = deviceId
        self.schema = schema
        self.packVersion = packVersion
        self.payload = payload
        self.origin = origin
    }

    /// The `type` column: the payload's type name (unknown types keep theirs).
    public var type: String { payload.typeName }
    public var key: EventKey { EventKey(at: at, id: id) }
    /// The local day the event belongs to (04:00 rollover in its own UTC offset).
    public var localDay: Int64 { LocalDay.dayNumber(ms: at, tzOffsetMinutes: tzOffsetMin) }
}

/// The typed payload of an event. Unknown types (from newer clients) and payloads this version can't decode keep
/// their raw JSON and are ignored by the reducer (docs/05 § Events).
public enum EventPayload: Hashable, Sendable {
    case introduced(IntroducedPayload)
    case attempt(AttemptPayload)
    case stepStarted(StepEventPayload)
    case stepCompleted(StepEventPayload)
    case glossTapped(GlossTappedPayload)
    case audioPlayed(AudioPlayedPayload)
    case session(SessionPayload)
    case checkCompleted(CheckCompletedPayload)
    case placementCompleted(PlacementCompletedPayload)
    case onboardingCompleted(OnboardingCompletedPayload)
    /// An event type this version doesn't know, or a payload it can't decode: the raw payload JSON, untouched.
    case unknown(type: String, json: Data)

    public var eventType: EventType? {
        switch self {
        case .introduced: .introduced
        case .attempt: .attempt
        case .stepStarted: .stepStarted
        case .stepCompleted: .stepCompleted
        case .glossTapped: .glossTapped
        case .audioPlayed: .audioPlayed
        case .session: .session
        case .checkCompleted: .checkCompleted
        case .placementCompleted: .placementCompleted
        case .onboardingCompleted: .onboardingCompleted
        case .unknown: nil
        }
    }

    public var typeName: String {
        if case .unknown(let type, _) = self { return type }
        return eventType?.rawValue ?? ""
    }
}

// MARK: - introduced

/// `introduced.via` (docs/05 § Events).
public enum IntroductionVia: String, Codable, Sendable, CaseIterable {
    case preview, story, note, sounds, placement, catchup, debug
}

public struct IntroducedItem: Codable, Hashable, Sendable {
    public var itemId: ItemID
    public var skills: [Skill]

    public init(itemId: ItemID, skills: [Skill]) {
        self.itemId = itemId
        self.skills = skills
    }
}

/// `{items: [{itemId, skills}], via, stepId?}`.
public struct IntroducedPayload: Codable, Hashable, Sendable {
    public var items: [IntroducedItem]
    public var via: IntroductionVia
    public var stepId: StepID?

    public init(items: [IntroducedItem], via: IntroductionVia, stepId: StepID? = nil) {
        self.items = items
        self.via = via
        self.stepId = stepId
    }

    /// Groups pairs into items (sorted by item ID, skills in skill order).
    public init(pairs: [ItemSkillPair], via: IntroductionVia, stepId: StepID? = nil) {
        var byItem: [ItemID: Set<Skill>] = [:]
        for pair in pairs { byItem[pair.itemId, default: []].insert(pair.skill) }
        self.items = byItem.keys.sorted().map { IntroducedItem(itemId: $0, skills: (byItem[$0] ?? []).sorted()) }
        self.via = via
        self.stepId = stepId
    }

    public var pairs: [ItemSkillPair] {
        items.flatMap { item in item.skills.map { ItemSkillPair(item.itemId, $0) } }
    }
}

// MARK: - attempt

/// `attempt.feedbackShown`.
public enum FeedbackShown: String, Codable, Sendable {
    case none, hint, answer
}

/// One target of an attempt with its own outcome (a match gives each pair's outcome to that pair's target).
public struct AttemptTarget: Codable, Hashable, Sendable {
    public var itemId: ItemID
    public var skill: Skill
    public var outcome: AttemptOutcome

    public init(itemId: ItemID, skill: Skill, outcome: AttemptOutcome) {
        self.itemId = itemId
        self.skill = skill
        self.outcome = outcome
    }

    public var pair: ItemSkillPair { ItemSkillPair(itemId, skill) }
}

/// `{exerciseId, turnId?, format, context, stepId?, sessionId, attemptIndex, outcome, targets, response?, mode,
/// latencyMs, feedbackShown}`.
public struct AttemptPayload: Codable, Hashable, Sendable {
    public var exerciseId: ExerciseID
    /// Conversation turns: the node answered.
    public var turnId: String?
    public var format: ExerciseFormat
    public var context: AttemptContext
    public var stepId: StepID?
    public var sessionId: String
    /// 1 or 2.
    public var attemptIndex: Int
    public var outcome: AttemptOutcome
    public var targets: [AttemptTarget]
    /// The learner's text, capped by `EventFactory` (200 closed formats, 2,000 writing and talk).
    public var response: String?
    public var mode: AnswerMode
    public var latencyMs: Int
    public var feedbackShown: FeedbackShown

    public init(exerciseId: ExerciseID, turnId: String? = nil, format: ExerciseFormat, context: AttemptContext,
                stepId: StepID? = nil, sessionId: String, attemptIndex: Int = 1, outcome: AttemptOutcome,
                targets: [AttemptTarget], response: String? = nil, mode: AnswerMode, latencyMs: Int = 0,
                feedbackShown: FeedbackShown = .none)
    {
        self.exerciseId = exerciseId
        self.turnId = turnId
        self.format = format
        self.context = context
        self.stepId = stepId
        self.sessionId = sessionId
        self.attemptIndex = attemptIndex
        self.outcome = outcome
        self.targets = targets
        self.response = response
        self.mode = mode
        self.latencyMs = latencyMs
        self.feedbackShown = feedbackShown
    }

    /// docs/05 § Replay: final when the outcome is final or this is the second attempt. In check, final and
    /// placement contexts there is one attempt only (docs/05 § Stepped feedback), so every answer there is final.
    public var isFinal: Bool {
        outcome.isFinal || attemptIndex >= 2 || context == .check || context == .final || context == .placement
    }
}

// MARK: - steps, glosses, audio

/// `stepStarted` / `stepCompleted`: `{stepId, sessionId, durationMs?}`.
public struct StepEventPayload: Codable, Hashable, Sendable {
    public var stepId: StepID
    public var sessionId: String
    public var durationMs: Int?

    public init(stepId: StepID, sessionId: String, durationMs: Int? = nil) {
        self.stepId = stepId
        self.sessionId = sessionId
        self.durationMs = durationMs
    }
}

/// `glossTapped`: `{textId, line, token, itemId?}` (line and token are 1-based line and token ordinals).
public struct GlossTappedPayload: Codable, Hashable, Sendable {
    public var textId: TextID
    public var line: Int
    public var token: Int
    public var itemId: ItemID?

    public init(textId: TextID, line: Int, token: Int, itemId: ItemID? = nil) {
        self.textId = textId
        self.line = line
        self.token = token
        self.itemId = itemId
    }
}

/// `audioPlayed.context`.
public enum AudioContext: String, Codable, Sendable {
    case story, fluency, exercise, item
}

/// `audioPlayed`: `{audioId, textId?, rate, playedMs, context}`.
public struct AudioPlayedPayload: Codable, Hashable, Sendable {
    public var audioId: AudioID
    public var textId: TextID?
    public var rate: Double
    public var playedMs: Int
    public var context: AudioContext

    public init(audioId: AudioID, textId: TextID? = nil, rate: Double, playedMs: Int, context: AudioContext) {
        self.audioId = audioId
        self.textId = textId
        self.rate = rate
        self.playedMs = playedMs
        self.context = context
    }
}

// MARK: - session

/// `session.kind`.
public enum SessionKind: String, Codable, Sendable {
    case lesson, review, check, placement, final
}

/// `session`: `{sessionId, kind, platform, startedAt, endedAt, activeSeconds}`.
public struct SessionPayload: Codable, Hashable, Sendable {
    public var sessionId: String
    public var kind: SessionKind
    public var platform: Platform
    public var startedAt: Int64
    public var endedAt: Int64
    public var activeSeconds: Int

    public init(sessionId: String, kind: SessionKind, platform: Platform, startedAt: Int64, endedAt: Int64,
                activeSeconds: Int)
    {
        self.sessionId = sessionId
        self.kind = kind
        self.platform = platform
        self.startedAt = startedAt
        self.endedAt = endedAt
        self.activeSeconds = activeSeconds
    }
}

// MARK: - checks and placement

/// `checkCompleted.kind`.
public enum CheckKind: String, Codable, Sendable {
    case unit, final
}

/// One section of a check result.
public struct CheckSectionResult: Codable, Hashable, Sendable {
    public var id: String
    public var earned: Double
    public var possible: Double
    /// The device couldn't do this section (speaking without speech recognition, or speaking switched off).
    public var excluded: Bool

    public init(id: String, earned: Double, possible: Double, excluded: Bool = false) {
        self.id = id
        self.earned = earned
        self.possible = possible
        self.excluded = excluded
    }

    /// earned / possible (0 when nothing was possible).
    public var fraction: Double { possible > 0 ? earned / possible : 0 }
}

/// `checkCompleted`: `{checkId, kind, sections, overall, passed, canDosReached}`.
public struct CheckCompletedPayload: Codable, Hashable, Sendable {
    public var checkId: CheckID
    public var kind: CheckKind
    public var sections: [CheckSectionResult]
    public var overall: Double
    public var passed: Bool
    public var canDosReached: [CanDoID]

    public init(checkId: CheckID, kind: CheckKind, sections: [CheckSectionResult], overall: Double, passed: Bool,
                canDosReached: [CanDoID])
    {
        self.checkId = checkId
        self.kind = kind
        self.sections = sections
        self.overall = overall
        self.passed = passed
        self.canDosReached = canDosReached
    }
}

/// One placement block result (`placementCompleted.blocks`). `correct` counts full credit as 1 and `almost` as
/// half, like check scoring (docs/05 § Unit check scoring).
public struct PlacementBlockResult: Codable, Hashable, Sendable {
    public var unit: UnitID
    public var correct: Double
    public var total: Double

    public init(unit: UnitID, correct: Double, total: Double) {
        self.unit = unit
        self.correct = correct
        self.total = total
    }
}

/// `placementCompleted`: `{startUnit, blocks}`.
public struct PlacementCompletedPayload: Codable, Hashable, Sendable {
    public var startUnit: UnitID
    public var blocks: [PlacementBlockResult]

    public init(startUnit: UnitID, blocks: [PlacementBlockResult]) {
        self.startUnit = startUnit
        self.blocks = blocks
    }
}

/// `onboardingCompleted`: `{reason, forms, country, beginner}`. Telemetry drops `country` (docs/12).
public struct OnboardingCompletedPayload: Codable, Hashable, Sendable {
    public var reason: String?
    public var forms: LearnerForms
    public var country: String?
    public var beginner: Bool

    public init(reason: String?, forms: LearnerForms, country: String?, beginner: Bool) {
        self.reason = reason
        self.forms = forms
        self.country = country
        self.beginner = beginner
    }
}
