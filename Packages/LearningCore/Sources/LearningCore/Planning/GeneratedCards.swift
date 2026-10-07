import Foundation

/// A near-miss answer of a generated recall card, in the shape of an exercise's `near` entry (docs/03): when the
/// normalised response equals an expansion of `answer`, grading returns `outcome` with `hint` as the note.
public struct GeneratedNearAnswer: Hashable, Sendable {
    /// An answer pattern.
    public var answer: String
    public var outcome: AttemptOutcome
    public var hint: String

    public init(answer: String, outcome: AttemptOutcome, hint: String) {
        self.answer = answer
        self.outcome = outcome
        self.hint = hint
    }
}

/// "Type the Italian for *croissant*" (docs/05 § Review session builder, docs/06 § 1).
public struct GeneratedRecallCard: Hashable, Sendable {
    public var exerciseId: ExerciseID
    public var itemId: ItemID
    /// The item's gloss up to the first `;`.
    public var promptEn: String
    /// The accepted answer pattern; its first expansion is the model answer.
    public var answer: String
    public var near: [GeneratedNearAnswer]
}

/// Italian (with audio) → pick the English gloss from up to 4 options.
public struct GeneratedReadCard: Hashable, Sendable {
    public var exerciseId: ExerciseID
    public var itemId: ItemID
    /// The display form shown (and voiced).
    public var promptIt: String
    /// Options as written; the player shows them in its seeded shuffle like any choice.
    public var options: [String]
    /// Index of the right gloss in `options`.
    public var answer: Int
}

/// Play one word of a sound pair and choose between the two.
public struct GeneratedListenCard: Hashable, Sendable {
    public var exerciseId: ExerciseID
    public var itemId: ItemID
    public var pair: [ContentIndex.SoundWord]
    /// Index in `pair` of the word played (and the answer).
    public var play: Int
}

/// A generated review card (`gen:<skill>:<itemId>`).
public enum GeneratedCard: Hashable, Sendable {
    case recall(GeneratedRecallCard)
    case read(GeneratedReadCard)
    case listen(GeneratedListenCard)

    public var exerciseId: ExerciseID {
        switch self {
        case .recall(let c): c.exerciseId
        case .read(let c): c.exerciseId
        case .listen(let c): c.exerciseId
        }
    }

    public var itemId: ItemID {
        switch self {
        case .recall(let c): c.itemId
        case .read(let c): c.itemId
        case .listen(let c): c.itemId
        }
    }

    /// The format the card is shown and logged as.
    public var format: ExerciseFormat {
        switch self {
        case .recall: .recall
        case .read: .choice
        case .listen: .soundPair
        }
    }
}

/// Builders for generated review cards. They produce answer-pattern *strings*; grading them is the graders' job.
public enum GeneratedCards {
    public static func exerciseId(skill: Skill, itemId: ItemID) -> ExerciseID {
        ExerciseID("gen:\(skill.rawValue):\(itemId.rawValue)")
    }

    // MARK: Recall

    /// The generated recall card for a word or chunk, or nil (grammar points and sounds get none; a chunk whose
    /// text contains `/` must set `recall_answer`).
    public static func recall(for item: ContentIndex.Item) -> GeneratedRecallCard? {
        guard item.kind == .word || item.kind == .chunk else { return nil }
        let id = exerciseId(skill: .recall, itemId: item.id)
        let prompt = item.primaryGloss
        if let pattern = item.recallAnswer, !pattern.isEmpty {
            return GeneratedRecallCard(exerciseId: id, itemId: item.id, promptEn: prompt, answer: pattern, near: [])
        }
        if item.kind == .chunk {
            guard let answer = chunkAnswer(item.it) else { return nil }
            return GeneratedRecallCard(exerciseId: id, itemId: item.id, promptEn: prompt, answer: escape(answer),
                                       near: [])
        }
        if item.pos == "noun", let noun = nounRecall(item) {
            return GeneratedRecallCard(exerciseId: id, itemId: item.id, promptEn: prompt, answer: noun.answer,
                                       near: noun.near)
        }
        return GeneratedRecallCard(exerciseId: id, itemId: item.id, promptEn: prompt, answer: "[\(escape(item.it))]",
                                   near: [])
    }

    /// A chunk's `it` without trailing `… ? !` (and spaces); nil when it contains `/`.
    public static func chunkAnswer(_ it: String) -> String? {
        var text = it.trimmingCharacters(in: .whitespaces)
        while let last = text.last, "…?!".contains(last) || last == " " { text.removeLast() }
        guard !text.isEmpty, !text.contains("/") else { return nil }
        return text
    }

    /// Escapes the pattern language's special characters in literal text (docs/03 § The answer-pattern language).
    public static func escape(_ text: String) -> String {
        var out = ""
        for ch in text {
            if "{[(|".contains(ch) { out.append("\\") }
            out.append(ch)
        }
        return out
    }

    struct NounForm: Hashable {
        var article: String
        var noun: String
        var elided: Bool

        var text: String { elided ? article + noun : article + " " + noun }
        var pattern: String { elided ? "[\(escape(article + noun))]" : "\(escape(article)) [\(escape(noun))]" }
    }

    static let definiteArticles: Set<String> = ["il", "lo", "la", "i", "gli", "le"]
    static let indefiniteArticles: Set<String> = ["un", "uno", "una"]

    /// `il cornetto` → (il, cornetto); `l'acqua` → (l', acqua, elided). Nil for a form without a leading article.
    static func parseNounForm(_ raw: String) -> NounForm? {
        let text = raw.replacingOccurrences(of: "’", with: "'").trimmingCharacters(in: .whitespaces)
        let lower = text.lowercased()
        for elided in ["un'", "l'"] where lower.hasPrefix(elided) && text.count > elided.count {
            let noun = String(text.dropFirst(elided.count)).trimmingCharacters(in: .whitespaces)
            return NounForm(article: elided, noun: noun, elided: true)
        }
        guard let space = text.firstIndex(of: " ") else { return nil }
        let article = String(text[..<space]).lowercased()
        guard definiteArticles.contains(article) || indefiniteArticles.contains(article) else { return nil }
        let noun = String(text[text.index(after: space)...]).trimmingCharacters(in: .whitespaces)
        return noun.isEmpty ? nil : NounForm(article: article, noun: noun, elided: false)
    }

    /// Removes a trailing gender mark: `l'acqua (f)` → `l'acqua`.
    static func stripGenderMark(_ text: String) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        for mark in [" (m)", " (f)", " (mf)", " (m/f)"] where trimmed.hasSuffix(mark) {
            return String(trimmed.dropLast(mark.count)).trimmingCharacters(in: .whitespaces)
        }
        return trimmed
    }

    static func forms(_ display: String?) -> [NounForm] {
        guard let display else { return [] }
        return stripGenderMark(display).split(separator: "/").compactMap { parseNounForm(String($0)) }
    }

    static func startsWithVowel(_ noun: String) -> Bool {
        guard let first = noun.lowercased().first else { return false }
        return "aeiouàèéìòóù".contains(first)
    }

    /// Nouns accept the definite or indefinite article with the noun as focus (`{il|un} [cornetto]`); a bare noun is
    /// `correctWithNote`; an article of the other gender with the right noun is `almost`.
    static func nounRecall(_ item: ContentIndex.Item) -> (answer: String, near: [GeneratedNearAnswer])? {
        var all: [NounForm] = []
        for form in forms(item.displayDef) + forms(item.displayIndef) where !all.contains(form) { all.append(form) }
        guard let model = all.first else { return nil }
        let nouns = all.map(\.noun).reduce(into: [String]()) { if !$0.contains($1) { $0.append($1) } }

        let answer: String
        if nouns.count == 1, all.allSatisfy({ !$0.elided }) {
            let articles = all.map { escape($0.article) }
            answer =
                articles.count == 1 ? model.pattern : "{\(articles.joined(separator: "|"))} [\(escape(model.noun))]"
        } else {
            answer = all.count == 1 ? model.pattern : "{\(all.map(\.pattern).joined(separator: "|"))}"
        }

        var near: [GeneratedNearAnswer] = []
        let bare = nouns.count == 1 ? escape(nouns[0]) : "{\(nouns.map(escape).joined(separator: "|"))}"
        near.append(GeneratedNearAnswer(answer: bare, outcome: .correctWithNote,
                                        hint: "Say it with its article: \(model.text)"))

        // The singular articles of the other gender (l' fits both, so it is never "wrong").
        if nouns.count == 1, let gender = item.gender, gender != .mf {
            let noun = nouns[0]
            let wrongArticles: [(String, Bool)] =
                gender == .m
                ? [("la", false), ("una", false)] + (startsWithVowel(noun) ? [("un'", true)] : [])
                : [("il", false), ("lo", false), ("un", false), ("uno", false)]
            let correct = Set(all.map(\.text))
            let wrong = wrongArticles.map { NounForm(article: $0.0, noun: noun, elided: $0.1).text }
                .filter { !correct.contains($0) }
            if !wrong.isEmpty {
                let gendered = gender == .m ? "masculine" : "feminine"
                let pattern = wrong.count == 1 ? escape(wrong[0]) : "{\(wrong.map(escape).joined(separator: "|"))}"
                near.append(GeneratedNearAnswer(answer: pattern, outcome: .almost,
                                                hint: "\(noun) is \(gendered): \(model.text)"))
            }
        }
        return (answer, near)
    }

    // MARK: Read

    /// The generated read card: the right gloss and up to three distractors, the glosses of eligible items
    /// (`pool`) with the same part of speech, preferring the same topic, drawn with the session RNG. When fewer than
    /// three share the part of speech, other eligible items fill the remaining options. Nil without any distractor.
    public static func read(for item: ContentIndex.Item, pool: [ContentIndex.Item], rng: inout SplitMix64)
        -> GeneratedReadCard?
    {
        guard item.kind == .word || item.kind == .chunk else { return nil }
        let right = item.primaryGloss
        var taken = Set([right.lowercased()] + item.altGlosses.map { $0.lowercased() })
        let others = pool.filter { $0.id != item.id && ($0.kind == .word || $0.kind == .chunk) }
            .sorted { $0.id < $1.id }
        let posKey = { (i: ContentIndex.Item) in i.pos ?? i.kind.rawValue }
        let topics = Set(item.topics)
        let samePOS = others.filter { posKey($0) == posKey(item) }
        let sameTopic = samePOS.filter { !topics.isDisjoint(with: $0.topics) }
        let otherTopic = samePOS.filter { topics.isDisjoint(with: $0.topics) }
        let rest = others.filter { posKey($0) != posKey(item) }

        var distractors: [String] = []
        for group in [sameTopic, otherTopic, rest] {
            for candidate in group.seededShuffle(using: &rng) where distractors.count < 3 {
                let gloss = candidate.primaryGloss
                guard !gloss.isEmpty, taken.insert(gloss.lowercased()).inserted else { continue }
                distractors.append(gloss)
            }
        }
        guard !distractors.isEmpty else { return nil }
        let answer = rng.nextInt(below: distractors.count + 1)
        var options = distractors
        options.insert(right, at: answer)
        return GeneratedReadCard(exerciseId: exerciseId(skill: .read, itemId: item.id), itemId: item.id,
                                 promptIt: item.displayForm, options: options, answer: answer)
    }

    // MARK: Listen

    /// The generated listen card for a sound: one pair and one of its words, both drawn with the session RNG.
    public static func listen(for sound: ContentIndex.Sound, rng: inout SplitMix64) -> GeneratedListenCard? {
        let pairs = sound.pairs.filter { $0.count == 2 }
        guard !pairs.isEmpty else { return nil }
        let pair = pairs[rng.nextInt(below: pairs.count)]
        return GeneratedListenCard(exerciseId: exerciseId(skill: .listen, itemId: sound.itemId), itemId: sound.itemId,
                                   pair: pair, play: rng.nextInt(below: 2))
    }
}
