#if FEEDBACK
    import FeedbackKit
    import SwiftUI

    /// In-app feedback, in Debug builds only (ADR-23; the `FEEDBACK` condition, `App/Config/Debug.xcconfig`): a
    /// shake, Help › Send Feedback… or Settings › Feedback opens FeedbackKit's form, and a screenshot shows a banner
    /// that offers it. The report goes to the owner's private inbox, j23n/feedback, where it's triaged before an
    /// issue is filed here. The screenshot shows the course, which content reports need, and nothing of the
    /// learner's own (`FeedbackPrivacy`). Each report carries the tab and the step on screen (`MainTabs`) and the
    /// loaded pack's version and content hash.
    extension FeedbackCenter {
        static func italiano(app: AppModel) -> FeedbackCenter {
            let center = FeedbackCenter(
                configuration: FeedbackConfiguration(
                    inbox: GitHubRepository(owner: "j23n", name: "feedback"),
                    app: "maestro",
                    kinds: [.bug, .idea, .content],
                    redaction: .privacySensitiveViews
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

    /// What a feedback screenshot hides, on the root view of each window: the learner's own words wherever a model
    /// answer, a hint or a transcript shows one (`PersonalWords`, which `ItalianText`, `MixedText` and the views that
    /// echo the learner's input check), the study ID, and, painted over by FeedbackKit, whatever is in a text field
    /// (a typed answer, the name in Settings). The course's own text stays.
    struct FeedbackPrivacy: ViewModifier {
        let app: AppModel
        let center: FeedbackCenter

        func body(content: Content) -> some View {
            content
                .environment(\.personalWords, PersonalWords(app.profile))
                .feedbackRedaction(center)
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
