import Foundation
import LearningCore
import Observation

// Shared pieces of every exercise view model (docs/05 § Grading, § Stepped feedback; docs/06 § Shared player
// behaviour). View models are platform-neutral (Foundation, Observation, LearningCore), so they compile and are
// tested on Linux too (scripts/check-app-logic.sh --test); the SwiftUI views only render them.

/// The per-target outcome an `attempt` event carries (docs/05 § Events: a match gives each pair its own outcome).
struct TargetOutcome: Sendable, Equatable {
    let itemID: ItemID
    let skill: Skill
    let outcome: AttemptOutcome
}

/// What one graded answer contributes to the event log. The lesson player turns it into an `attempt` event
/// (adding sessionId, stepId and context) and appends it through the learner store.
struct AttemptDraft: Sendable, Equatable {
    let exerciseID: ExerciseID
    let turnID: String?
    let format: ExerciseFormat
    let attemptIndex: Int
    let outcome: AttemptOutcome
    let targets: [TargetOutcome]
    let response: String?
    let mode: AnswerMode
    let latencyMs: Int
    let feedbackShown: FeedbackMachine.FeedbackShown
    /// What a unit check scores for this exercise when it isn't the outcome alone: points found (talk, writing),
    /// or goals completed (conversation). The check recorder keeps the latest one per exercise (docs/05 § Checks).
    var checkAnswer: CheckAnswer? = nil
}

@MainActor
protocol AttemptSink: AnyObject {
    func record(_ draft: AttemptDraft)
}

/// Collects drafts in tests and previews.
@MainActor
final class RecordingAttemptSink: AttemptSink {
    private(set) var drafts: [AttemptDraft] = []
    func record(_ draft: AttemptDraft) { drafts.append(draft) }
}

/// Everything an exercise model needs besides its payload.
struct ExerciseEnvironment: Sendable {
    var context: AttemptContext
    var profile: LearnerProfile
    var knownForms: KnownForms
    /// The pack's letter names: spoken spelling in transcripts (*M A R C O* reads *emme a erre ci o*; docs/05 § Speech
    /// transcripts). Every speaking format passes it to its matcher.
    var letterNames: LetterNames = .none
    /// Milliseconds now (the app's Clock); used for latency only.
    var nowMs: @Sendable () -> Int64
    /// Speech is available and switched on (docs/09): shows "Say it" and the mic.
    var canSpeak: Bool

    static func preview(context: AttemptContext = .lesson) -> ExerciseEnvironment {
        ExerciseEnvironment(context: context, profile: .unspecified, knownForms: .empty, nowMs: { 0 }, canSpeak: false)
    }
}

/// What the feedback panel shows (docs/06 § Shared player behaviour, `TryAgain.png`).
struct FeedbackPresentation: Sendable, Equatable {
    enum Tone: Sendable, Equatable { case success, hint, answer }

    let tone: Tone
    let headline: String
    let detail: String?
    /// The answer to show (the model answer, or the correction for `almost`).
    let answer: String?
    /// The one-line rule shown with the answer.
    let rule: String?
    let canTryAgain: Bool
    let canShowAnswer: Bool
    let canContinue: Bool
}

enum FeedbackCopy {
    /// Short, warm headlines in sentence case (docs/07 § Copy). English UI only; Italian comes from the pack.
    static func headline(for hint: FeedbackMachine.Hint?, kind: HintKind?) -> String {
        if case .nearMiss? = hint { return "Not quite." }
        switch kind {
        case .realWord?: return "Close. That's a real word."
        case .ending?: return "Close. Check the ending."
        case .spelling?: return "Almost. Check the spelling."
        case .missing?: return "Something's missing."
        case .extra?: return "There's an extra word."
        case nil: return "Not quite."
        }
    }

    /// What speech recognition heard, for a spoken answer (docs/09: it may say "I heard: …", never judge
    /// pronunciation).
    static func heard(_ transcript: String) -> String { "I heard: “\(transcript)”" }

    static let success = "That's right."
    static let successWithNote = "That's right. Mind the accents."
    static let successWithCorrection = "Almost: just a small slip."
    static let successAfterHint = "That's it."
    static let failedTwice = "Here's the answer."
    static let revealed = "Here's the answer."
}

/// Wraps a FeedbackMachine with the bookkeeping every format shares: latency from when the exercise (or the retry)
/// appeared, and turning machine records into drafts.
@MainActor
struct AttemptClock {
    private var startedAt: Int64
    private let now: @Sendable () -> Int64

    init(now: @escaping @Sendable () -> Int64) {
        self.now = now
        startedAt = now()
    }

    mutating func restart() { startedAt = now() }

    func latencyMs() -> Int { Int(max(0, now() - startedAt)) }
}

extension AttemptOutcome {
    var isSuccess: Bool { self == .correct || self == .correctWithNote || self == .almost }
}

extension ExercisePayload {
    /// Every primary target gets the exercise's outcome (docs/05 § Events), except match (per pair).
    func targetOutcomes(_ outcome: AttemptOutcome, skillOverride: Skill? = nil) -> [TargetOutcome] {
        targets.map { TargetOutcome(itemID: $0.itemId, skill: skillOverride ?? $0.skill, outcome: outcome) }
    }

    /// Closed-format responses are kept to 200 characters, writing and talk to 2,000 (docs/05 § Events).
    static func clip(_ response: String, format: ExerciseFormat) -> String {
        let limit = (format == .writing || format == .talk) ? 2_000 : 200
        return response.count > limit ? String(response.prefix(limit)) : response
    }
}
