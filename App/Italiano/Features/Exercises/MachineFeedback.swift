import Foundation
import LearningCore

/// The feedback panel for formats whose grading has no typed correction to show (dictation, sentence building,
/// relay, choice): built from the stepped-feedback state alone. Assessments show nothing (docs/06 § Unit check).
enum MachineFeedback {
    static func presentation(
        state: FeedbackMachine.State, context: AttemptContext, answer: String?, rule: String?,
        hintHeadline: String = "Not quite.", canShowAnswer: Bool
    ) -> FeedbackPresentation? {
        if context.isAssessment { return nil }
        switch state {
        case .awaitingFirst, .awaitingSecond:
            return nil
        case .hinted(let hint):
            return FeedbackPresentation(
                tone: .hint, headline: hintHeadline, detail: hint?.text,
                answer: nil, rule: nil, canTryAgain: true, canShowAnswer: canShowAnswer, canContinue: false)
        case .answerShown(let reason):
            return FeedbackPresentation(
                tone: .answer, headline: reason == .revealed ? FeedbackCopy.revealed : FeedbackCopy.failedTwice,
                detail: nil, answer: answer, rule: rule, canTryAgain: false, canShowAnswer: false, canContinue: true)
        case .done(let result):
            switch result {
            case .success, .successWithCorrection:
                return FeedbackPresentation(
                    tone: .success, headline: FeedbackCopy.success, detail: nil, answer: nil, rule: nil,
                    canTryAgain: false, canShowAnswer: false, canContinue: true)
            case .successAfterHint:
                return FeedbackPresentation(
                    tone: .success, headline: FeedbackCopy.successAfterHint, detail: nil, answer: nil, rule: nil,
                    canTryAgain: false, canShowAnswer: false, canContinue: true)
            case .failed, .skipped:
                return FeedbackPresentation(
                    tone: .answer, headline: FeedbackCopy.failedTwice, detail: nil, answer: answer, rule: rule,
                    canTryAgain: false, canShowAnswer: false, canContinue: true)
            }
        }
    }
}
