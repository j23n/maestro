import Foundation
import LearningCore

/// Turns exercise drafts into `attempt` events (docs/05 § Events) and hands them to the learner store. The player
/// owns one per activity: it knows the context, the session and the current step; the exercise models know the rest.
@MainActor
final class EventAttemptSink: AttemptSink {
    let factory: EventFactory
    let context: AttemptContext
    let sessionID: String
    /// The step on screen; nil in review sessions.
    var stepID: StepID?
    private let write: @MainActor (Event) -> Void

    init(factory: EventFactory, context: AttemptContext, sessionID: String, stepID: StepID? = nil,
         write: @escaping @MainActor (Event) -> Void)
    {
        self.factory = factory
        self.context = context
        self.sessionID = sessionID
        self.stepID = stepID
        self.write = write
    }

    func record(_ d: AttemptDraft) {
        let event = factory.attempt(
            exerciseId: d.exerciseID, turnId: d.turnID, format: d.format, context: context, stepId: stepID,
            sessionId: sessionID, attemptIndex: d.attemptIndex, outcome: d.outcome,
            targets: d.targets.map { ItemSkillPair($0.itemID, $0.skill) },
            pairOutcomes: d.format == .match ? d.targets.map(\.outcome) : nil, response: d.response, mode: d.mode,
            latencyMs: d.latencyMs, feedbackShown: FeedbackShown(rawValue: d.feedbackShown.rawValue) ?? .none)
        write(event)
    }
}
