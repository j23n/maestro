import Foundation

/// Why a pair is in a review session.
public enum CardSource: String, Hashable, Sendable {
    /// A failed-check focus item (reviewed first, due or not).
    case focus
    /// A scheduled pair due by the end of today.
    case due
    /// A scheduled pair introduced by placement that has no memory yet (the new catch-up queue).
    case catchUp
}

/// One card of a review session.
public struct ReviewCard: Hashable, Sendable {
    public var pair: ItemSkillPair
    public var source: CardSource
    public var exercise: CardExercise
    /// A card answered Again first time, shown again at the end of the session.
    public var isRequeue: Bool
    public var itemKind: ItemKind

    public init(pair: ItemSkillPair, source: CardSource, exercise: CardExercise, isRequeue: Bool = false,
                itemKind: ItemKind)
    {
        self.pair = pair
        self.source = source
        self.exercise = exercise
        self.isRequeue = isRequeue
        self.itemKind = itemKind
    }

    public var format: ExerciseFormat { exercise.format }
    public var exerciseId: ExerciseID { exercise.id }
    public var isGrammar: Bool { itemKind == .grammar }
}

/// A pair waiting for review, with the keys it is ordered by.
public struct ScheduledPair: Hashable, Sendable {
    public var pair: ItemSkillPair
    public var source: CardSource
    /// Nil when the pair has no memory yet.
    public var due: Int64?
    /// Current retrievability (0 without memory).
    public var retrievability: Double
}

/// A built review session. The player shows `cards` in order and calls `ReviewSessionBuilder.requeueIfNeeded`
/// after each first answer.
public struct ReviewSession: Hashable, Sendable {
    public enum Kind: String, Hashable, Sendable {
        case review, catchUp
    }

    public let sessionId: String
    public let kind: Kind
    public internal(set) var cards: [ReviewCard]
    var requeued: Set<ItemSkillPair> = []
    /// The session RNG, continued for re-queued generated cards.
    var rng: SplitMix64

    public init(sessionId: String, kind: Kind, cards: [ReviewCard], rng: SplitMix64) {
        self.sessionId = sessionId
        self.kind = kind
        self.cards = cards
        self.rng = rng
    }

    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.sessionId == rhs.sessionId && lhs.kind == rhs.kind && lhs.cards == rhs.cards
            && lhs.requeued == rhs.requeued
    }

    public func hash(into hasher: inout Hasher) {
        hasher.combine(sessionId)
        hasher.combine(cards)
    }
}

/// Builds review sessions (docs/05 § Review session builder).
///
/// 1. Order: focus items first (due or not), then due date ascending, then lowest current retrievability, then
///    `(itemId, skill)`; only pairs with an eligible exercise or generated card; at most one skill per item.
///    Size = min(due + focus, 20); due cards also stop at what is left of the daily review limit.
/// 2. One exercise per card (`CardSelector`), never the same exercise twice in a session.
/// 3. Interleave with the session RNG (SplitMix64 seeded by FNV-1a 64 of the session ID).
/// 4. A card answered Again first time is re-queued once at the end, with a different exercise if one exists.
public struct ReviewSessionBuilder: Sendable {
    public let content: ContentIndex
    public let state: LearnerState
    public let selector: CardSelector
    public var sessionTarget: Int
    public var dailyLimit: Int
    public var catchUpPerDay: Int

    static let fsrs = FSRS6()

    public init(content: ContentIndex, state: LearnerState, device: DeviceCapabilities = DeviceCapabilities(),
                sessionTarget: Int = 20, dailyLimit: Int = 60, catchUpPerDay: Int = 15)
    {
        self.content = content
        self.state = state
        self.selector = CardSelector(content: content, state: state, device: device)
        self.sessionTarget = sessionTarget
        self.dailyLimit = dailyLimit
        self.catchUpPerDay = catchUpPerDay
    }

    // MARK: Ordering

    /// Focus and due pairs that have a card today, in session priority order, one skill per item, not truncated.
    public func orderedPairs(now: Int64, tzOffsetMinutes: Int) -> [ScheduledPair] {
        let today = LocalDay.dayNumber(ms: now, tzOffsetMinutes: tzOffsetMinutes)
        let endOfToday = LocalDay.endMs(dayNumber: today, tzOffsetMinutes: tzOffsetMinutes)
        var entries: [ScheduledPair] = []
        var focusPairs = Set<ItemSkillPair>()
        for pair in state.activeFocus(now: now) {
            // A focus pair already reviewed today waits until tomorrow.
            if let memory = state.memory[pair],
                LocalDay.dayNumber(ms: memory.lastReviewMs, tzOffsetMinutes: tzOffsetMinutes) >= today
            {
                continue
            }
            guard content.item(pair.itemId) != nil, selector.hasCard(for: pair, now: now) else { continue }
            focusPairs.insert(pair)
            entries.append(entry(pair, source: .focus, now: now))
        }
        for pair in content.scheduledPairs where !focusPairs.contains(pair) {
            guard let memory = state.memory[pair], memory.dueMs <= endOfToday,
                selector.hasCard(for: pair, now: now)
            else { continue }
            entries.append(entry(pair, source: .due, now: now))
        }
        entries.sort { a, b in
            let ka = (a.source == .focus ? 0 : 1, a.due ?? Int64.min, a.retrievability)
            let kb = (b.source == .focus ? 0 : 1, b.due ?? Int64.min, b.retrievability)
            if ka != kb { return ka < kb }
            return a.pair < b.pair
        }
        var items = Set<ItemID>()
        return entries.filter { items.insert($0.pair.itemId).inserted }
    }

    func entry(_ pair: ItemSkillPair, source: CardSource, now: Int64) -> ScheduledPair {
        guard let memory = state.memory[pair] else {
            return ScheduledPair(pair: pair, source: source, due: nil, retrievability: 0)
        }
        return ScheduledPair(pair: pair, source: source, due: memory.dueMs,
                             retrievability: Self.fsrs.retrievability(memory, atMs: now))
    }

    /// How many more review cards today's daily limit allows.
    public func remainingDailyAllowance(now: Int64, tzOffsetMinutes: Int) -> Int {
        let today = LocalDay.dayNumber(ms: now, tzOffsetMinutes: tzOffsetMinutes)
        return max(0, dailyLimit - state.activity(day: today).cardsReviewed)
    }

    /// Placement-introduced scheduled pairs with no memory yet that have a card, in course order.
    public func catchUpPairs(now: Int64) -> [ItemSkillPair] {
        var items = Set<ItemID>()
        return content.scheduledPairs.filter { pair in
            state.introductions[pair]?.via == .placement && state.memory[pair] == nil
        }.sorted { a, b in
            let ua = content.item(a.itemId).flatMap { content.unitOrd($0.unitId) } ?? Int.max
            let ub = content.item(b.itemId).flatMap { content.unitOrd($0.unitId) } ?? Int.max
            return ua != ub ? ua < ub : a < b
        }.filter { selector.hasCard(for: $0, now: now) && items.insert($0.itemId).inserted }
    }

    /// New catch-up cards still allowed today (15 a day).
    public func catchUpAllowance(now: Int64, tzOffsetMinutes: Int) -> Int {
        let today = LocalDay.dayNumber(ms: now, tzOffsetMinutes: tzOffsetMinutes)
        return max(0, catchUpPerDay - (state.catchUpStarted[today] ?? 0))
    }

    // MARK: Building

    /// A review session of focus and due cards.
    public func build(sessionId: String, now: Int64, tzOffsetMinutes: Int) -> ReviewSession {
        let ordered = orderedPairs(now: now, tzOffsetMinutes: tzOffsetMinutes)
        var dueLeft = remainingDailyAllowance(now: now, tzOffsetMinutes: tzOffsetMinutes)
        var rng = SplitMix64(seedString: sessionId)
        var used = Set<ExerciseID>()
        var cards: [ReviewCard] = []
        for entry in ordered where cards.count < sessionTarget {
            if entry.source == .due {
                guard dueLeft > 0 else { break }
            }
            guard let card = makeCard(entry.pair, source: entry.source, now: now, used: &used, rng: &rng) else {
                continue
            }
            if entry.source == .due { dueLeft -= 1 }
            cards.append(card)
        }
        let ordered2 = Interleaver.interleave(cards, rng: &rng)
        return ReviewSession(sessionId: sessionId, kind: .review, cards: ordered2, rng: rng)
    }

    /// A session of new catch-up cards (after placement), at most the day's remaining allowance.
    public func buildCatchUp(sessionId: String, now: Int64, tzOffsetMinutes: Int) -> ReviewSession {
        let allowance = min(sessionTarget, catchUpAllowance(now: now, tzOffsetMinutes: tzOffsetMinutes))
        var rng = SplitMix64(seedString: sessionId)
        var used = Set<ExerciseID>()
        var cards: [ReviewCard] = []
        for pair in catchUpPairs(now: now) where cards.count < allowance {
            if let card = makeCard(pair, source: .catchUp, now: now, used: &used, rng: &rng) { cards.append(card) }
        }
        let ordered = Interleaver.interleave(cards, rng: &rng)
        return ReviewSession(sessionId: sessionId, kind: .catchUp, cards: ordered, rng: rng)
    }

    func makeCard(_ pair: ItemSkillPair, source: CardSource, now: Int64, used: inout Set<ExerciseID>,
                  rng: inout SplitMix64) -> ReviewCard?
    {
        guard let item = content.item(pair.itemId),
            let exercise = selector.select(pair, now: now, excluding: used, rng: &rng)
        else { return nil }
        used.insert(exercise.id)
        return ReviewCard(pair: pair, source: source, exercise: exercise, itemKind: item.kind)
    }

    // MARK: Re-queue

    /// After a card's first answer: if it rated Again, append it once more at the end of the session with a
    /// different exercise if one exists (another eligible bank exercise not used in this session, else a
    /// generated card, else the same exercise). Returns whether a card was added.
    @discardableResult
    public func requeueIfNeeded(_ session: inout ReviewSession, cardIndex: Int, outcome: AttemptOutcome,
                                mode: AnswerMode, now: Int64) -> Bool
    {
        guard session.cards.indices.contains(cardIndex) else { return false }
        let card = session.cards[cardIndex]
        guard !card.isRequeue, !session.requeued.contains(card.pair),
            RatingPolicy.rating(format: card.format, outcome: outcome, mode: mode, attemptIndex: 1,
                                context: .review) == .again
        else { return false }
        let used = Set(session.cards.map(\.exerciseId))
        let exercise: CardExercise
        if let other = selector.candidates(for: card.pair, now: now, excluding: used, allowRecent: true).first {
            exercise = .bank(other.id, other.format)
        } else if !card.exercise.isGenerated, let generated = selector.generate(card.pair, rng: &session.rng) {
            exercise = .generated(generated)
        } else {
            exercise = card.exercise
        }
        session.cards.append(ReviewCard(pair: card.pair, source: card.source, exercise: exercise, isRequeue: true,
                                        itemKind: card.itemKind))
        session.requeued.insert(card.pair)
        return true
    }
}
