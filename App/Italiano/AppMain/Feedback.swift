#if FEEDBACK
import FeedbackKit
import Foundation

/// In-app feedback, in Debug builds only (ADR-23; the `FEEDBACK` condition, `Config/Debug.xcconfig`): a shake, a
/// screenshot, Help › Send Feedback… or Settings › Feedback opens FeedbackKit's form, and the report goes to the
/// owner's private inbox, j23n/feedback, where it's triaged before an issue is filed here. Its screenshot shows course
/// content and the learner's answers, which aren't private values, so nothing is redacted. Each report carries the
/// tab and the step on screen (`MainTabs`) and the pack the build bundles.
extension FeedbackCenter {
    static func italiano(config: AppConfig) -> FeedbackCenter {
        let center = FeedbackCenter(configuration: FeedbackConfiguration(
            inbox: GitHubRepository(owner: "j23n", name: "feedback"),
            app: "maestro",
            kinds: [.bug, .idea, .content]
        ))
        let pack = config.pack.rawValue
        center.additionalContext = { [ContextItem(name: "Pack", value: pack)] }
        return center
    }
}
#endif
