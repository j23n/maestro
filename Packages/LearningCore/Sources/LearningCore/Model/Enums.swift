import Foundation

/// The four skills memory is kept for (docs/01 glossary, docs/05 § Skills).
public enum Skill: String, Codable, Sendable, CaseIterable, Comparable {
    case read, listen, recall, speak

    /// Order used for sorting (read, listen, recall, speak).
    public var rank: Int {
        switch self {
        case .read: 0
        case .listen: 1
        case .recall: 2
        case .speak: 3
        }
    }

    public static func < (lhs: Skill, rhs: Skill) -> Bool { lhs.rank < rhs.rank }
}

/// Per item and skill: produce, recognise, or (grammar) taught as a chunk (docs/01 glossary).
public enum ItemStatus: String, Codable, Sendable {
    case P, R, chunk
}

/// Step kinds (`steps.kind` in the pack; docs/06).
public enum StepKind: String, Codable, Sendable, CaseIterable {
    case opener, preview, story, listening, reading, note, practice, sounds, use
    case conversation, talk, writing, relay, fluency, check
}

/// Exercise formats (`exercises.format`; docs/06).
public enum ExerciseFormat: String, Codable, Sendable, CaseIterable {
    case cloze, recall
    case sentenceBuilding = "sentence-building"
    case dictation
    case soundPair = "sound-pair"
    case `repeat`
    case choice, match
    case trueFalse = "true-false"
    case relay, conversation, talk, writing

    /// docs/05 § Rating policy: the format families.
    public enum Family: Sendable { case typed, tapped, spoken, task }

    public var family: Family {
        switch self {
        case .cloze, .recall, .dictation, .sentenceBuilding: .typed
        case .choice, .match, .trueFalse, .soundPair: .tapped
        case .repeat: .spoken
        case .conversation, .talk, .writing, .relay: .task
        }
    }
}

/// `exercises.role` in the pack.
public enum ExerciseRole: String, Codable, Sendable {
    case learn, check, placement, final, comprehension
}

/// The outcome of one graded answer (docs/05 § Events, `attempt.outcome`).
public enum AttemptOutcome: String, Codable, Sendable, CaseIterable {
    case correct, correctWithNote, almost, wrong, revealed, skipped

    /// docs/05 § Replay: an attempt is final when its outcome is one of these, or when `attemptIndex` is 2.
    public var isFinal: Bool {
        switch self {
        case .correct, .correctWithNote, .almost, .revealed, .skipped: true
        case .wrong: false
        }
    }

    /// Check scoring (docs/05 § Unit check scoring): full, half or nothing.
    public var checkCredit: Double {
        switch self {
        case .correct, .correctWithNote: 1
        case .almost: 0.5
        case .wrong, .revealed, .skipped: 0
        }
    }
}

/// How the learner answered.
public enum AnswerMode: String, Codable, Sendable {
    case typed, spoken, tapped
}

/// Where an attempt happened (`attempt.context`).
public enum AttemptContext: String, Codable, Sendable {
    case lesson, review, check, placement, final
}

/// FSRS ratings (docs/05 § FSRS-6). Easy is not used by the MVP's rating policy but is part of FSRS.
public enum FSRSRating: Int, Codable, Sendable, CaseIterable {
    case again = 1, hard = 2, good = 3, easy = 4
}

/// The learner's chosen forms (`profile.forms`, docs/08).
public enum LearnerForms: String, Codable, Sendable {
    case m, f, both
}

/// The device family a session ran on (`session.platform`, docs/05; the sync status line, docs/08).
public enum Platform: String, Codable, Sendable {
    case iPhone, iPad, Mac
}
