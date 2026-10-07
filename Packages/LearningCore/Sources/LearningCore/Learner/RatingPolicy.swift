import Foundation

/// Events → FSRS ratings (docs/05 § Rating policy). Only first attempts update FSRS; Easy is never produced.
public enum RatingPolicy {
    /// The FSRS rating for one target of an attempt, or nil when the attempt makes no update.
    public static func rating(format: ExerciseFormat, outcome: AttemptOutcome, mode: AnswerMode,
                              attemptIndex: Int, context: AttemptContext) -> FSRSRating?
    {
        guard attemptIndex == 1 else { return nil }  // second attempts and reveals after a hint are learning
        if context == .placement { return nil }  // placement introduces items, it never invents memory
        if outcome == .skipped { return nil }
        // Conversation turns, talk, writing, relay: task-level evidence only, however they were answered.
        if format.family == .task { return nil }

        // Spoken answers (repeat, or recall answered with "Say it"): a pass is Good; a fail is logged only (ADR-08).
        if mode == .spoken {
            switch outcome {
            case .correct, .correctWithNote: return .good
            default: return nil
            }
        }

        switch format.family {
        case .typed:
            switch outcome {
            case .correct, .correctWithNote: return .good
            case .almost: return .hard
            case .wrong, .revealed: return .again
            case .skipped: return nil
            }
        case .tapped:
            switch outcome {
            case .correct, .correctWithNote: return .good
            case .almost, .wrong, .revealed: return .again
            case .skipped: return nil
            }
        case .spoken:
            // A repeat answered any way but by voice (never in the MVP) still makes no update.
            return nil
        case .task:
            return nil
        }
    }
}
