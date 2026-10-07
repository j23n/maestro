import Foundation

/// What this device can do (speech availability and the `speech.enabled` setting).
public struct DeviceCapabilities: Hashable, Sendable {
    public var speechAvailable: Bool
    public var speechEnabled: Bool

    public init(speechAvailable: Bool = true, speechEnabled: Bool = true) {
        self.speechAvailable = speechAvailable
        self.speechEnabled = speechEnabled
    }

    public var canUseSpeech: Bool { speechAvailable && speechEnabled }
}

/// The exercise a review card shows: a bank exercise from the pack, or a generated card.
public enum CardExercise: Hashable, Sendable {
    case bank(ExerciseID, ExerciseFormat)
    case generated(GeneratedCard)

    public var id: ExerciseID {
        switch self {
        case .bank(let id, _): id
        case .generated(let card): card.exerciseId
        }
    }

    public var format: ExerciseFormat {
        switch self {
        case .bank(_, let format): format
        case .generated(let card): card.format
        }
    }

    public var isGenerated: Bool {
        if case .generated = self { return true }
        return false
    }
}

/// Picks one exercise per review card (docs/05 § Review session builder, step 2).
///
/// Candidates are learn exercises whose targets include the pair, that are eligible, not shown in the last 2 days
/// and suitable for this device. Preferred formats by skill come first; among them the format least recently used
/// for this item wins (then preference order), and within a format the exercise shown least recently (then ID).
/// Without a candidate it generates a card (`gen:<skill>:<itemId>`); grammar points get none, so they wait.
public struct CardSelector: Sendable {
    public let content: ContentIndex
    public let state: LearnerState
    public let device: DeviceCapabilities

    /// Exercises shown more recently than this are not candidates.
    public static let recentWindowMs: Int64 = 2 * LocalDay.msPerDay

    public init(content: ContentIndex, state: LearnerState, device: DeviceCapabilities = DeviceCapabilities()) {
        self.content = content
        self.state = state
        self.device = device
    }

    /// recall → recall, cloze, sentence-building, dictation; read → choice (Italian → English), match;
    /// listen → sound-pair, choice with audio.
    public static func preferredFormats(for skill: Skill) -> [ExerciseFormat] {
        switch skill {
        case .recall: [.recall, .cloze, .sentenceBuilding, .dictation]
        case .read: [.choice, .match]
        case .listen: [.soundPair, .choice]
        case .speak: [.repeat]
        }
    }

    /// Speech-only formats need speech recognition that is available and switched on.
    public func isSuitable(_ exercise: ContentIndex.Exercise) -> Bool {
        exercise.format != .repeat || device.canUseSpeech
    }

    /// Ranked bank candidates for a pair. `allowRecent` lifts the 2-day rule (re-queued cards).
    public func candidates(for pair: ItemSkillPair, now: Int64, excluding: Set<ExerciseID> = [],
                           allowRecent: Bool = false) -> [ContentIndex.Exercise]
    {
        let all = content.exercises(targeting: pair).filter { exercise in
            exercise.role == .learn && !excluding.contains(exercise.id) && isSuitable(exercise)
                && Eligibility.isEligible(exercise: exercise, state: state)
                && (allowRecent || !shownRecently(exercise.id, now: now))
        }
        return rank(all, for: pair)
    }

    func shownRecently(_ id: ExerciseID, now: Int64) -> Bool {
        guard let last = state.exerciseHistory[id]?.lastAt else { return false }
        return now - last < Self.recentWindowMs
    }

    /// Preferred formats only (when any is available); least recently used format for the item first.
    func rank(_ exercises: [ContentIndex.Exercise], for pair: ItemSkillPair) -> [ContentIndex.Exercise] {
        let preferred = Self.preferredFormats(for: pair.skill)
        let inPreferred = exercises.filter { preferred.contains($0.format) }
        let pool = inPreferred.isEmpty ? exercises : inPreferred
        let lastUsed = state.formatLastUsed[pair.itemId] ?? [:]
        func key(_ e: ContentIndex.Exercise) -> (Int64, Int, String, Int64, String) {
            (lastUsed[e.format] ?? Int64.min, preferred.firstIndex(of: e.format) ?? preferred.count,
             e.format.rawValue, state.exerciseHistory[e.id]?.lastAt ?? Int64.min, e.id.rawValue)
        }
        return pool.sorted { key($0) < key($1) }
    }

    /// Eligible items a generated read card may draw distractors from: words and chunks introduced for `read`.
    public func readDistractorPool() -> [ContentIndex.Item] {
        content.items.filter {
            ($0.kind == .word || $0.kind == .chunk) && state.isIntroduced(ItemSkillPair($0.id, .read))
        }
    }

    /// Whether a generated card exists for the pair (no RNG needed to know).
    public func canGenerate(_ pair: ItemSkillPair) -> Bool {
        guard state.isIntroduced(pair), let item = content.item(pair.itemId) else { return false }
        switch pair.skill {
        case .recall:
            return GeneratedCards.recall(for: item) != nil
        case .read:
            guard item.kind == .word || item.kind == .chunk else { return false }
            var probe = SplitMix64(seed: 0)
            return GeneratedCards.read(for: item, pool: readDistractorPool(), rng: &probe) != nil
        case .listen:
            guard item.kind == .sound, let sound = content.sound(item.id) else { return false }
            return sound.pairs.contains { $0.count == 2 }
        case .speak:
            return false
        }
    }

    /// The generated card for a pair, drawing from the session RNG.
    public func generate(_ pair: ItemSkillPair, rng: inout SplitMix64) -> GeneratedCard? {
        guard state.isIntroduced(pair), let item = content.item(pair.itemId) else { return nil }
        switch pair.skill {
        case .recall:
            return GeneratedCards.recall(for: item).map { .recall($0) }
        case .read:
            return GeneratedCards.read(for: item, pool: readDistractorPool(), rng: &rng).map { .read($0) }
        case .listen:
            guard item.kind == .sound, let sound = content.sound(item.id) else { return nil }
            return GeneratedCards.listen(for: sound, rng: &rng).map { .listen($0) }
        case .speak:
            return nil
        }
    }

    /// The pair has a card today: an eligible bank candidate, or a generated card.
    public func hasCard(for pair: ItemSkillPair, now: Int64) -> Bool {
        !candidates(for: pair, now: now).isEmpty || canGenerate(pair)
    }

    /// One exercise for the card, or nil when the pair has to wait.
    public func select(_ pair: ItemSkillPair, now: Int64, excluding: Set<ExerciseID> = [],
                       rng: inout SplitMix64) -> CardExercise?
    {
        if let best = candidates(for: pair, now: now, excluding: excluding).first {
            return .bank(best.id, best.format)
        }
        guard let generated = generate(pair, rng: &rng), !excluding.contains(generated.exerciseId) else { return nil }
        return .generated(generated)
    }
}
