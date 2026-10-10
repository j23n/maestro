#if FEEDBACK
    import FeedbackKit
    import SwiftUI

    /// In-app feedback, in Debug builds only (ADR-23; the `FEEDBACK` condition, `Config/Debug.xcconfig`): a
    /// shake, Help › Send Feedback… or Settings › Feedback opens FeedbackKit's form, and a screenshot shows a banner
    /// that offers it. The report goes to the owner's private inbox, j23n/feedback, where it's triaged before an
    /// issue is filed here. Its screenshot shows course content and the learner's answers, which aren't private
    /// values, so nothing is redacted. Each report carries the tab and the step on screen (`MainTabs`) and the
    /// loaded pack's version and content hash.
    extension FeedbackCenter {
        static func italiano(app: AppModel) -> FeedbackCenter {
            let center = FeedbackCenter(
                configuration: FeedbackConfiguration(
                    inbox: GitHubRepository(owner: "j23n", name: "feedback"),
                    app: "maestro",
                    kinds: [.bug, .idea, .content]
                ))
            center.additionalContext = { [weak app] in
                guard let content = app?.content else { return [] }
                return [
                    ContextItem(name: "Pack", value: content.packVersion),
                    ContextItem(name: "Content hash", value: String(content.contentHash.prefix(12))),
                ]
            }
            return center
        }
    }

    /// Settings › Feedback: FeedbackKit's settings are a `Form` section, so they open in a sheet of their own rather
    /// than in Settings' scroll view.
    struct FeedbackSettingsSheet: View {
        let center: FeedbackCenter
        @Environment(\.dismiss) private var dismiss

        var body: some View {
            NavigationStack {
                Form {
                    FeedbackSettingsSection(center: center)
                }
                .formStyle(.grouped)
                .navigationTitle("Feedback")
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                            .accessibilityLabel(Text("Close the feedback settings"))
                            .accessibilityIdentifier("settings.feedback.done")
                    }
                }
            }
            .presentationSizing(.form)
        }
    }
#endif
