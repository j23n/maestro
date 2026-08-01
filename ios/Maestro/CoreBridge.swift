// ⚠️ UNTESTED SCAFFOLD — written off-Mac against the UniFFI-generated API
// (core/bindings/swift/maestro_core.swift). Expect small compile fixes.
//
// The only file that talks to the core. Everything crossing the boundary
// is JSON; the Codable structs here mirror core/src/model.rs exactly.

import Foundation

// MARK: - Codable mirrors of core/src/model.rs

struct PlannedActivity: Codable, Identifiable {
    let itemId: String
    let itemType: String
    let slot: String
    var id: String { itemId }

    enum CodingKeys: String, CodingKey {
        case itemId = "item_id", itemType = "item_type", slot
    }
}

/// A slot the composer could not fill — the pack ran out of eligible
/// items. Surfaced so a thin lesson reads as missing content, not as a
/// complete session.
struct Shortfall: Codable {
    let slot: String
    let requested: UInt32
    let filled: UInt32
}

struct SessionPlan: Codable {
    let scenarioId: String?
    let archetype: String
    let activities: [PlannedActivity]
    let targetGrammar: [String]
    let shortfalls: [Shortfall]

    enum CodingKeys: String, CodingKey {
        case scenarioId = "scenario_id", archetype, activities
        case targetGrammar = "target_grammar", shortfalls
    }
}

struct GrammarState: Codable {
    let mastery: Double?
    /// Mastery band: new | weak | developing | consolidated.
    let label: String
    /// The grammar point's name, e.g. "Saluti e congedi". Show this, never
    /// the id — the core falls back to the id only on pre-label bundles.
    let displayName: String
    let introduced: Bool

    enum CodingKeys: String, CodingKey {
        case mastery, label, introduced
        case displayName = "display_name"
    }
}

struct CanDoState: Codable {
    let status: String
    /// The can-do statement itself — the learner-facing progress spine.
    let label: String
    let grammarMastered: UInt32, grammarTotal: UInt32
    let functionsDemonstrated: UInt32, functionsTotal: UInt32

    enum CodingKeys: String, CodingKey {
        case status, label
        case grammarMastered = "grammar_mastered", grammarTotal = "grammar_total"
        case functionsDemonstrated = "functions_demonstrated"
        case functionsTotal = "functions_total"
    }
}

/// Rough CEFR classification. Secondary to can-dos by design — see
/// `folds::classify_cefr`. Always render `confidence` next to `level`:
/// the level is an estimate from however much evidence exists, and how
/// much that is varies enormously.
struct CefrClassification: Codable {
    let level: String
    let source: String
    let estimated: String
    let assessed: String?
    let confidence: String
    let grammarMastered: UInt32, grammarEncountered: UInt32, grammarTotal: UInt32

    enum CodingKeys: String, CodingKey {
        case level, source, estimated, assessed, confidence
        case grammarMastered = "grammar_mastered"
        case grammarEncountered = "grammar_encountered"
        case grammarTotal = "grammar_total"
    }

    /// "A1 · based on 3 of 10 grammar points" — the level with its working
    /// shown, so it can't be mistaken for an assessed result.
    var summary: String {
        source == "assessed"
            ? "\(level) · from a level test"
            : "\(level) · based on \(grammarMastered) of \(grammarTotal) grammar points"
    }
}

struct Progress: Codable {
    let grammar: [String: GrammarState]
    let canDos: [String: CanDoState]
    let cefr: CefrClassification
    let currentPhase: UInt32

    enum CodingKeys: String, CodingKey {
        case grammar, canDos = "can_dos", cefr
        case currentPhase = "current_phase"
    }
}

struct DrillPayload: Codable {
    let prompt: String
    let choices: [String]?
}

struct ReadingPayload: Codable {
    let title: String
    let text: String?
    let turns: [DialogueTurn]?
    let glossary: [String: String]?
    let questionIds: [String]

    enum CodingKeys: String, CodingKey {
        case title, text, turns, glossary, questionIds = "question_ids"
    }
}

struct DialogueTurn: Codable {
    let speaker: String
    let text: String
}

/// A learner-facing reference page for one grammar point. Shown at the
/// head of an introduction session, before the grammar is drilled.
struct GrammarRefPayload: Codable {
    let grammarId: String
    let title: String
    let bodyMd: String
    let examples: [String]

    enum CodingKeys: String, CodingKey {
        case grammarId = "grammar_id", title, examples
        case bodyMd = "body_md"
    }
}

struct VocabCardPayload: Codable {
    let lemma: String
    let front: String
    let back: String
    let example: String?
    let exampleGloss: String?

    enum CodingKeys: String, CodingKey {
        case lemma, front, back, example
        case exampleGloss = "example_gloss"
    }
}

struct WritingPayload: Codable {
    let prompt: String
    let minWords: Int
    /// Grammar the submission is expected to attempt, and vocabulary it
    /// should reach for — the offline rubric checks both.
    let requiredGrammar: [String]
    let requiredVocab: [String]
    let modelAnswer: String?

    enum CodingKeys: String, CodingKey {
        case prompt
        case minWords = "min_words"
        case requiredGrammar = "required_grammar"
        case requiredVocab = "required_vocab"
        case modelAnswer = "model_answer"
    }
}

struct SpeakingPayload: Codable {
    let prompt: String
    let targetText: String
    let variants: [String]

    enum CodingKeys: String, CodingKey {
        case prompt, variants
        case targetText = "target_text"
    }
}

/// One word in the pack's vocabulary, with whatever the learner has done
/// with it. Lemmas the pack hasn't authored a card for still appear —
/// they're readable inventory, they just have no `itemId` to practise.
struct VocabEntry: Codable, Identifiable {
    let lemma: String
    let cefrLevel: String
    let pos: String
    let gloss: String
    let itemId: String?
    let front: String?
    let back: String?
    let example: String?
    let exampleGloss: String?
    /// SM-2's streak, which a lapse resets. `reviews` is the honest count.
    let repetitions: Int
    let reviews: Int
    let intervalDays: Int
    let easeFactor: Double
    /// Negative when overdue; nil for a word never met.
    let dueInDays: Int?
    /// Days since the word first appeared in a lesson; nil if it hasn't.
    let firstSeenDaysAgo: Int?
    let status: String

    var id: String { lemma }
    var isPractisable: Bool { itemId != nil }

    enum CodingKeys: String, CodingKey {
        case lemma, pos, gloss, example, repetitions, reviews, status
        case cefrLevel = "cefr_level"
        case itemId = "item_id"
        case front, back
        case exampleGloss = "example_gloss"
        case intervalDays = "interval_days"
        case easeFactor = "ease_factor"
        case dueInDays = "due_in_days"
        case firstSeenDaysAgo = "first_seen_days_ago"
    }
}

/// A spec id with the name to show for it.
struct SpecLabel: Codable, Identifiable {
    let id: String
    let label: String
}

/// What a lesson is about, and how far the learner has got with it. Shown
/// before a session as a splash and after one as the recap's framing.
struct LessonBrief: Codable {
    let scenarioId: String
    let cefrLevel: String
    let label: String
    let description: String
    let overview: String
    let sceneSetting: String
    let outro: String
    /// Media path for `media(at:)`; empty when unillustrated.
    let image: String
    let grammar: [SpecLabel]
    let functions: [SpecLabel]
    let completedDepths: Int
    let depthCount: Int

    /// True the first time through — the splash leads with the scene, and
    /// on a replay the learner has already read it.
    var isFirstVisit: Bool { completedDepths == 0 }

    enum CodingKeys: String, CodingKey {
        case label, description, overview, outro, image, grammar, functions
        case scenarioId = "scenario_id"
        case cefrLevel = "cefr_level"
        case sceneSetting = "scene_setting"
        case completedDepths = "completed_depths"
        case depthCount = "depth_count"
    }
}

/// A problem the learner reported. `packVersion` matters: the same item id
/// can be fixed and re-shipped, so a flag without it can't be told apart
/// from one already dealt with.
struct Flag: Codable, Identifiable {
    let itemId: String
    let note: String?
    let packVersion: String?
    let at: Int64?

    var id: String { "\(itemId)-\(at ?? 0)" }

    enum CodingKeys: String, CodingKey {
        case note, at
        case itemId = "item_id"
        case packVersion = "pack_version"
    }
}

// MARK: - Bridge

@Observable
final class CoreBridge {
    private let core: Core  // from maestro_core.swift (UniFFI)

    init() throws {
        let support = try FileManager.default.url(
            for: .applicationSupportDirectory, in: .userDomainMask,
            appropriateFor: nil, create: true)
        // Installed pack wins; the bundled fixture is the first-run fallback.
        let installed = support.appendingPathComponent("it.pack.sqlite")
        let packPath = FileManager.default.fileExists(atPath: installed.path)
            ? installed.path
            : Bundle.main.path(forResource: "it.pack", ofType: "sqlite")!
        let learnerPath = support.appendingPathComponent("learner.sqlite").path
        core = try Core.open(packPath: packPath, learnerDbPath: learnerPath)
    }

    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }

    func composeSession(minutes: UInt32 = 15) throws -> SessionPlan {
        let options: [String: Any] = [
            "now": Int(Date().timeIntervalSince1970),
            "time_budget_minutes": minutes,
            "seed": UInt64.random(in: 0 ..< .max),
        ]
        let json = try core.composeSession(
            optionsJson: String(
                data: JSONSerialization.data(withJSONObject: options), encoding: .utf8)!)
        return try decode(SessionPlan.self, json)
    }

    func progress() throws -> Progress {
        try decode(Progress.self, core.progressSummary(now: Int64(Date().timeIntervalSince1970)))
    }

    /// The whole vocabulary, spec order. Small enough (hundreds of rows)
    /// to hand over in one go rather than paging.
    func vocabulary() throws -> [VocabEntry] {
        try decode(
            [VocabEntry].self,
            core.vocabInventory(now: Int64(Date().timeIntervalSince1970)))
    }

    /// What the next session will be about, without composing it. nil when
    /// the learner has finished everything unlocked.
    func nextLesson() throws -> LessonBrief? {
        try decode(
            LessonBrief?.self,
            core.nextLessonBrief(now: Int64(Date().timeIntervalSince1970)))
    }

    func lesson(scenarioId: String) throws -> LessonBrief? {
        try decode(
            LessonBrief?.self,
            core.lessonBrief(
                scenarioId: scenarioId, now: Int64(Date().timeIntervalSince1970)))
    }

    func itemPayload<T: Decodable>(_ type: T.Type, id: String) throws -> T {
        try decode(type, core.getItemJson(itemId: id))
    }

    func itemPayloadRaw(id: String) throws -> String {
        try core.getItemJson(itemId: id)
    }

    func score(itemId: String, response: String) throws -> ScoreResult {
        try core.scoreAttempt(itemId: itemId, response: response)
    }

    /// Record a scored attempt. evidence comes from the item payload's
    /// `evidence` array, passed through untouched.
    func recordAttempt(
        itemId: String, outcome: String, modality: String,
        evidenceClass: String, evidenceJson: [[String: Any]], response: String?
    ) throws {
        var event: [String: Any] = [
            "type": "attempt", "item_id": itemId, "outcome": outcome,
            "modality": modality, "evidence_class": evidenceClass,
            "evidence": evidenceJson,
        ]
        if let response { event["response"] = response }
        try record(event)
    }

    /// The item's `evidence` array, passed to the core verbatim. Every
    /// activity view needs it to record an event, so it lives here rather
    /// than being re-derived in each one.
    func evidence(for itemId: String) -> [[String: Any]] {
        guard let json = try? core.getItemJson(itemId: itemId),
              let obj = try? JSONSerialization.jsonObject(with: Data(json.utf8))
                  as? [String: Any],
              let evidence = obj["evidence"] as? [[String: Any]]
        else { return [] }
        return evidence
    }

    /// Mark grammar as taught. The composer's `introduction` archetype
    /// exists because these points are new; without this event they stay
    /// new forever and every session re-introduces them.
    func recordIntroduced(evidenceJson: [[String: Any]]) throws {
        try record([
            "type": "introduced",
            "at": Int(Date().timeIntervalSince1970),
            "evidence": evidenceJson,
        ])
    }

    /// Close out a lesson. `pick_scenario` orders by completion count, so
    /// without this the composer offers the same scenario forever and
    /// lessons 2+ are unreachable. Emitted once, at the end of a session.
    func recordScenarioCompleted(scenarioId: String, depth: UInt8 = 1) throws {
        try record([
            "type": "scenario_completed",
            "at": Int(Date().timeIntervalSince1970),
            "scenario_id": scenarioId,
            "depth": depth,
        ])
    }

    /// Add the words an activity contains to the learner's vocabulary.
    /// Recorded when the activity is shown rather than when it is answered:
    /// meeting a word is what puts it in your vocabulary, whether or not
    /// you got the exercise right.
    ///
    /// Only vocab-axis evidence is sent. The grammar on the same item is
    /// deliberately left out — marking it introduced here would cost the
    /// learner the reference page the introduction session owes them.
    func recordEncountered(itemId: String, evidenceJson: [[String: Any]]) throws {
        let vocab = evidenceJson.filter { $0["axis"] as? String == "vocab" }
        guard !vocab.isEmpty else { return }
        try record([
            "type": "encountered",
            "at": Int(Date().timeIntervalSince1970),
            "item_id": itemId,
            "evidence": vocab,
        ])
    }

    /// The spec lemmas an item contains, for a recap that wants to name
    /// the words without re-reading the whole inventory.
    func vocabIds(for itemId: String) -> [String] {
        evidence(for: itemId).compactMap {
            $0["axis"] as? String == "vocab" ? $0["id"] as? String : nil
        }
    }

    /// A vocab card review. `srsRating` is the SM-2 grade (1–5) that
    /// drives the card's next due date.
    func recordVocabReview(
        itemId: String, srsRating: UInt8, evidenceJson: [[String: Any]]
    ) throws {
        try record([
            "type": "attempt",
            "at": Int(Date().timeIntervalSince1970),
            "item_id": itemId,
            "outcome": srsRating >= 3 ? "correct" : "incorrect",
            "modality": "vocab",
            "evidence_class": "targeted",
            "srs_rating": srsRating,
            "evidence": evidenceJson,
        ])
    }

    // MARK: - Pending feedback

    /// Queue a submission for the LLM tier. Queuing is unconditional and
    /// offline: the job waits in the learner record until a backend is
    /// both available and allowed by its eval gate.
    @discardableResult
    func enqueueFeedbackJob(
        kind: String, itemId: String, submission: String, context: [String: String]
    ) throws -> Int64 {
        let request: [String: Any] = [
            "kind": kind, "item_id": itemId, "submission": submission,
            "context": context,
        ]
        return try core.enqueueFeedbackJob(
            requestJson: String(
                data: JSONSerialization.data(withJSONObject: request), encoding: .utf8)!)
    }

    func pendingFeedbackJobs() throws -> [String] {
        try core.listPendingFeedbackJobs()
    }

    /// Mark a job answered. The core stamps `feedback_source` with the
    /// backend name and folds any evidence event back automatically.
    func completeFeedbackJob(id: Int64, backend: String, feedbackText: String) throws {
        let result: [String: Any] = ["feedback_text": feedbackText]
        try core.completeFeedbackJob(
            jobId: id, backend: backend,
            resultJson: String(
                data: JSONSerialization.data(withJSONObject: result), encoding: .utf8)!)
    }

    // MARK: - Problem reports

    /// Report a problem with an item, in the learner's own words. Inert by
    /// design: the core stores it and the fold ignores it, so reporting
    /// never nudges mastery.
    func flagItem(itemId: String, note: String) throws {
        try core.flagItem(itemId: itemId, note: note)
    }

    func flags() throws -> [Flag] {
        try core.listFlags().map { try decode(Flag.self, $0) }
    }

    /// The flags as a file to hand off — Files, AirDrop, mail, whatever the
    /// share sheet offers. Narrower than a backup on purpose: reporting a
    /// typo shouldn't mean sending your whole learning history.
    func exportFlagsFile() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("maestro-flags.jsonl")
        try core.exportFlags().write(to: url, atomically: true, encoding: .utf8)
        return url
    }

    private func record(_ event: [String: Any]) throws {
        try core.recordEvent(
            eventJson: String(
                data: JSONSerialization.data(withJSONObject: event), encoding: .utf8)!)
    }

    func alignSpeech(target: String, transcript: String) -> AlignmentResult {
        alignTranscript(target: target, transcript: transcript)
    }
}
