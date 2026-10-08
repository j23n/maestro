import Foundation
import LearningCore
import Observation

// A review session (docs/05 § Review session builder, docs/06 § 17; `LibroPhone.png`, `Complete.png`): the engine
// builds the cards; this plays them one by one through the same exercise models as lessons, re-queues a card
// answered Again first time, and sums the session up at the end. Platform-neutral and tested.

/// Turns a generated review card (`gen:<skill>:<item>`) into an exercise payload, through the payload contract
/// (`schemas/pack-payloads.schema.json`), so the lesson exercise models play it unchanged.
enum GeneratedPayloads {
    static func payload(for card: GeneratedCard, unit: UnitID, display: (ItemID) -> WordInfo?) -> ExercisePayload? {
        var body: [String: Any]
        let skill: Skill
        var near: [[String: Any]] = []
        switch card {
        case .recall(let c):
            skill = .recall
            body = [
                "promptEn": c.promptEn, "contextIt": NSNull(), "answer": pattern(c.answer),
                "answerAudioId": orNull(display(c.itemId)?.audioID?.rawValue),
            ]
            near = c.near.map { ["answer": pattern($0.answer), "outcome": $0.outcome.rawValue, "hint": $0.hint] }
        case .read(let c):
            skill = .read
            body = [
                "promptIt": tokenized(c.promptIt), "promptAudioId": orNull(display(c.itemId)?.audioID?.rawValue),
                "audioTextId": NSNull(), "plays": NSNull(), "questionEn": "What does it mean?",
                "options": c.options.map { ["text": $0, "it": NSNull()] }, "answer": c.answer,
            ]
        case .listen(let c):
            skill = .listen
            body = [
                "question": "which-word",
                "pair": c.pair.map { ["it": $0.it, "gloss": NSNull(), "audioId": orNull($0.audioId?.rawValue)] },
                "play": c.play, "word": NSNull(), "answer": NSNull(), "tipEn": NSNull(),
            ]
        }
        let common: [String: Any] = [
            "id": card.exerciseId.rawValue, "format": card.format.rawValue, "role": "learn", "unitId": unit.rawValue,
            "stepId": NSNull(), "score": 1, "targets": [["itemId": card.itemId.rawValue, "skill": skill.rawValue]],
            "tags": [], "source": NSNull(), "hint": NSNull(), "rule": NSNull(), "near": near, "audioAfter": false,
        ]
        body.merge(common) { a, _ in a }
        guard let data = try? JSONSerialization.data(withJSONObject: body) else { return nil }
        return try? JSONDecoder().decode(ExercisePayload.self, from: data)
    }

    private static func orNull(_ s: String?) -> Any {
        if let s { return s }
        return NSNull()
    }

    private static func pattern(_ source: String) -> [String: Any] { ["source": source, "expansions": []] }

    private static func tokenized(_ text: String) -> [String: Any] { ["text": text, "lead": "", "tokens": []] }
}

/// Wraps the event sink: records each card's first-attempt outcome for re-queueing and the summary.
@MainActor
final class ReviewAttemptSink: AttemptSink {
    let inner: (any AttemptSink)?
    private(set) var firstOutcome: [ExerciseID: (AttemptOutcome, AnswerMode)] = [:]

    init(inner: (any AttemptSink)?) { self.inner = inner }

    func record(_ draft: AttemptDraft) {
        if draft.attemptIndex == 1, firstOutcome[draft.exerciseID] == nil {
            firstOutcome[draft.exerciseID] = (draft.outcome, draft.mode)
        }
        inner?.record(draft)
    }
}

@MainActor
@Observable
final class ReviewSessionModel {
    struct Summary: Equatable {
        let remembered: Int
        let total: Int
        /// The items answered Again first time ("To practise again").
        let practiseAgain: [ItemID]
        /// Cards whose item had no memory before this session (catch-up cards after placement).
        let newWords: Int
    }

    private(set) var session: ReviewSession
    private(set) var index = 0
    private(set) var host: ExerciseHostModel?
    /// The payload behind `host` (bank or generated).
    private(set) var payload: ExercisePayload?
    @ObservationIgnored private let builder: ReviewSessionBuilder
    @ObservationIgnored private let payloads: (ReviewCard) -> ExercisePayload?
    @ObservationIgnored private let env: ExerciseEnvironment
    @ObservationIgnored let sink: ReviewAttemptSink
    @ObservationIgnored private let newPairs: Set<ItemSkillPair>

    init(
        session: ReviewSession, builder: ReviewSessionBuilder, env: ExerciseEnvironment, sink: (any AttemptSink)?,
        newPairs: Set<ItemSkillPair> = [], payloads: @escaping (ReviewCard) -> ExercisePayload?
    ) {
        self.session = session
        self.newPairs = newPairs
        self.builder = builder
        self.env = env
        self.sink = ReviewAttemptSink(inner: sink)
        self.payloads = payloads
        makeHost()
    }

    var isFinished: Bool { index >= session.cards.count }
    var currentCard: ReviewCard? { session.cards[safe: index] }
    var progress: Double { session.cards.isEmpty ? 1 : Double(index) / Double(session.cards.count) }
    /// "3 / 20"
    var counter: String { "\(min(index + 1, session.cards.count)) / \(session.cards.count)" }

    /// Continue after a card: re-queue it if its first answer was Again (docs/05), then the next card.
    func advance() {
        guard let card = currentCard else { return }
        if let (outcome, mode) = sink.firstOutcome[card.exerciseId] {
            builder.requeueIfNeeded(&session, cardIndex: index, outcome: outcome, mode: mode, now: env.nowMs())
        }
        index += 1
        makeHost()
    }

    var summary: Summary {
        let firsts = session.cards.filter { !$0.isRequeue }
        let remembered = firsts.filter { card in
            guard let (o, mode) = sink.firstOutcome[card.exerciseId] else { return false }
            return RatingPolicy.rating(
                format: card.format, outcome: o, mode: mode, attemptIndex: 1,
                context: .review) != .again
        }
        let again = session.cards.filter(\.isRequeue).map(\.pair.itemId)
        var seen: Set<ItemID> = []
        return Summary(
            remembered: remembered.count, total: firsts.count,
            practiseAgain: again.filter { seen.insert($0).inserted },
            newWords: Set(firsts.map(\.pair)).intersection(newPairs).count)
    }

    private func makeHost() {
        guard let card = currentCard else {
            host = nil
            payload = nil
            return
        }
        // A card whose payload can't be built is skipped rather than shown broken.
        if let p = payloads(card), let h = ExerciseHostModel.make(p, env: env, sink: sink) {
            host = h
            payload = p
        } else {
            index += 1
            makeHost()
        }
    }
}

/// The session-complete card (`Complete.png`): what was remembered, new words, the Again items, the next review and
/// the week against the goal.
struct CompleteContent: Sendable, Equatable {
    let remembered: String
    let newWords: String
    /// Italian display forms, joined: "il conto, vorrei, cassa"; nil when nothing needs practising.
    let practiseAgain: String?
    let nextReview: String?
    let weekLine: String

    init(summary: ReviewSessionModel.Summary, words: [ItemID: WordInfo], nextReview: String?, week: WeekProgress) {
        remembered = "\(summary.remembered) of \(summary.total)"
        newWords = "\(summary.newWords)"
        practiseAgain = summary.practiseAgain.isEmpty
            ? nil : summary.practiseAgain.map { words[$0]?.display ?? $0.rawValue }.joined(separator: ", ")
        self.nextReview = nextReview
        weekLine = Self.weekLine(week)
    }

    /// "4 of 5 days this week. One more and you've met your goal."
    static func weekLine(_ w: WeekProgress) -> String {
        let head = "\(w.activeDays) of \(w.goal) days this week."
        switch w.goal - w.activeDays {
        case ...0: return "\(head) You've met your goal."
        case 1: return "\(head) One more and you've met your goal."
        case let n: return "\(head) \(n) more to meet your goal."
        }
    }
}
