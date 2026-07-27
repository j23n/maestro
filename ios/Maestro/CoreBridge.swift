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

struct SessionPlan: Codable {
    let scenarioId: String?
    let archetype: String
    let activities: [PlannedActivity]
    let targetGrammar: [String]

    enum CodingKeys: String, CodingKey {
        case scenarioId = "scenario_id", archetype, activities
        case targetGrammar = "target_grammar"
    }
}

struct GrammarState: Codable {
    let mastery: Double?
    let label: String
    let introduced: Bool
}

struct CanDoState: Codable {
    let status: String
    let grammarMastered: UInt32, grammarTotal: UInt32
    let functionsDemonstrated: UInt32, functionsTotal: UInt32

    enum CodingKeys: String, CodingKey {
        case status
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
        try core.recordEvent(
            eventJson: String(
                data: JSONSerialization.data(withJSONObject: event), encoding: .utf8)!)
    }

    func alignSpeech(target: String, transcript: String) -> AlignmentResult {
        alignTranscript(target: target, transcript: transcript)
    }
}
