import Foundation

/// Creates this device's events: IDs from `UUIDSource`, time from `Clock`, `schema` 1, `origin` local.
///
/// - Times are strictly increasing per factory (`at = max(now, previous + 1)`), so this device's events replay in the
///   order they were written even when two land in the same millisecond (an attempt and the `checkCompleted` that
///   follows it, for example). Pass the last local event's `at` when creating a factory after launch.
/// - `response` is capped at 200 characters for closed formats and 2,000 for writing and talk (docs/05 § Events).
/// - Targets follow docs/05: every target of a non-match exercise gets the exercise's outcome, a match gives each
///   pair's outcome to that pair's target, conversation turns carry none, and a recall answered by voice records its
///   targets under `speak` (docs/06 § 7).
public final class EventFactory: @unchecked Sendable {
    // @unchecked: `lastAt` is the only mutable state and is guarded by `lock`; clock and ID source are Sendable.
    public let deviceId: String
    public let packVersion: String
    private let clock: any Clock
    private let ids: any UUIDSource
    private let lock = NSLock()
    private var lastAt: Int64

    public static let closedResponseLimit = 200
    public static let longResponseLimit = 2_000

    public init(deviceId: String, packVersion: String, clock: any Clock, ids: any UUIDSource,
                lastAt: Int64 = Int64.min)
    {
        self.deviceId = deviceId
        self.packVersion = packVersion
        self.clock = clock
        self.ids = ids
        self.lastAt = lastAt
    }

    // MARK: Generic

    /// Wraps any payload in a new envelope.
    public func make(_ payload: EventPayload) -> Event {
        let (at, tz) = lock.withLock { () -> (Int64, Int) in
            let now = clock.nowMs()
            let at = lastAt == Int64.min ? now : max(now, lastAt + 1)
            lastAt = at
            return (at, clock.tzOffsetMinutes())
        }
        return Event(id: ids.next(), at: at, tzOffsetMin: tz, deviceId: deviceId, schema: Event.currentSchema,
                     packVersion: packVersion, payload: payload, origin: .local)
    }

    // MARK: Typed helpers

    /// `introduced` for these pairs, or nil when there is nothing to introduce.
    public func introduced(_ pairs: [ItemSkillPair], via: IntroductionVia, stepId: StepID? = nil) -> Event? {
        guard !pairs.isEmpty else { return nil }
        return make(.introduced(IntroducedPayload(pairs: pairs, via: via, stepId: stepId)))
    }

    public func introduced(_ payload: IntroducedPayload) -> Event? {
        payload.items.isEmpty ? nil : make(.introduced(payload))
    }

    /// One graded answer. `targets` are the exercise's primary targets in order; `pairOutcomes` are a match's
    /// per-pair outcomes (same length as `targets`).
    public func attempt(exerciseId: ExerciseID, turnId: String? = nil, format: ExerciseFormat,
                        context: AttemptContext, stepId: StepID? = nil, sessionId: String, attemptIndex: Int = 1,
                        outcome: AttemptOutcome, targets: [ItemSkillPair], pairOutcomes: [AttemptOutcome]? = nil,
                        response: String? = nil, mode: AnswerMode, latencyMs: Int,
                        feedbackShown: FeedbackShown = .none) -> Event
    {
        let payload = AttemptPayload(
            exerciseId: exerciseId, turnId: turnId, format: format, context: context, stepId: stepId,
            sessionId: sessionId, attemptIndex: attemptIndex, outcome: outcome,
            targets: Self.attemptTargets(format: format, mode: mode, targets: targets, outcome: outcome,
                                         pairOutcomes: pairOutcomes),
            response: Self.cap(response, format: format), mode: mode, latencyMs: latencyMs,
            feedbackShown: feedbackShown)
        return make(.attempt(payload))
    }

    public func stepStarted(_ stepId: StepID, sessionId: String) -> Event {
        make(.stepStarted(StepEventPayload(stepId: stepId, sessionId: sessionId)))
    }

    public func stepCompleted(_ stepId: StepID, sessionId: String, durationMs: Int? = nil) -> Event {
        make(.stepCompleted(StepEventPayload(stepId: stepId, sessionId: sessionId, durationMs: durationMs)))
    }

    public func glossTapped(textId: TextID, line: Int, token: Int, itemId: ItemID?) -> Event {
        make(.glossTapped(GlossTappedPayload(textId: textId, line: line, token: token, itemId: itemId)))
    }

    public func audioPlayed(audioId: AudioID, textId: TextID?, rate: Double, playedMs: Int,
                            context: AudioContext) -> Event
    {
        make(.audioPlayed(AudioPlayedPayload(audioId: audioId, textId: textId, rate: rate, playedMs: playedMs,
                                             context: context)))
    }

    public func session(sessionId: String, kind: SessionKind, platform: Platform, startedAt: Int64,
                        endedAt: Int64, activeSeconds: Int) -> Event
    {
        make(.session(SessionPayload(sessionId: sessionId, kind: kind, platform: platform, startedAt: startedAt,
                                     endedAt: endedAt, activeSeconds: activeSeconds)))
    }

    public func checkCompleted(_ payload: CheckCompletedPayload) -> Event {
        make(.checkCompleted(payload))
    }

    public func placementCompleted(_ payload: PlacementCompletedPayload) -> Event {
        make(.placementCompleted(payload))
    }

    public func onboardingCompleted(_ payload: OnboardingCompletedPayload) -> Event {
        make(.onboardingCompleted(payload))
    }

    // MARK: Rules

    /// The response limit for a format: 2,000 characters for writing and talk transcripts, 200 otherwise.
    public static func responseLimit(for format: ExerciseFormat) -> Int {
        switch format {
        case .writing, .talk: longResponseLimit
        default: closedResponseLimit
        }
    }

    /// Truncates a response to the format's limit, counting characters (grapheme clusters).
    public static func cap(_ response: String?, format: ExerciseFormat) -> String? {
        guard let response else { return nil }
        let limit = responseLimit(for: format)
        return response.count > limit ? String(response.prefix(limit)) : response
    }

    /// docs/05 § Events (Targets) and docs/06 § 7.
    public static func attemptTargets(format: ExerciseFormat, mode: AnswerMode, targets: [ItemSkillPair],
                                      outcome: AttemptOutcome, pairOutcomes: [AttemptOutcome]?) -> [AttemptTarget]
    {
        if format == .conversation { return [] }
        let perPair = format == .match && pairOutcomes?.count == targets.count ? pairOutcomes : nil
        return targets.enumerated().map { index, pair in
            let skill = format == .recall && mode == .spoken && pair.skill == .recall ? Skill.speak : pair.skill
            return AttemptTarget(itemId: pair.itemId, skill: skill, outcome: perPair?[index] ?? outcome)
        }
    }
}
