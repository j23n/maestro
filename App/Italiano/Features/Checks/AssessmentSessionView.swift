import LearningCore
import SwiftUI

/// One item at a time in a sitting that isn't a step (placement, the final A1 check; docs/06 §19–20): close, a
/// progress bar, the section line, then the exercise through the lesson views. These contexts show no feedback, so
/// an item ends with Continue, or moves straight on after Check.
struct AssessmentSessionView: View {
    /// "Unit 2 questions", "Listening"
    let title: String?
    let progress: Double
    /// "12 / 40" (nil when the length isn't known in advance: placement can stop early)
    let counter: String?
    let host: ExerciseHostModel?
    let payload: ExercisePayload?
    /// Changes with every item, so each gets a fresh view.
    let position: Int
    let bundle: LessonBundle
    let services: PlayerServices
    let onClose: () -> Void
    let onContinue: () -> Void
    /// The Debug menu, for the auto-answer bar (M6.3); nil in builds without it.
    var debug: DebugMenuModel? = nil

    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: Tokens.Space.s) {
                HStack(spacing: Tokens.Space.l) {
                    Button {
                        services.audio.stop()
                        onClose()
                    } label: {
                        Image(systemName: "xmark").font(.system(size: 20, weight: .medium))
                            .foregroundStyle(Color.ds.ink)
                            .frame(width: Tokens.Size.minTouch, height: Tokens.Size.minTouch)
                    }
                    .buttonStyle(.plain)
                    .keyboardShortcut(.cancelAction)
                    .accessibilityLabel(Text("Close"))
                    .accessibilityIdentifier("player.close")
                    DSProgressBar(value: progress)
                        .accessibilityLabel(Text("Progress"))
                        .accessibilityValue(Text("\(Int((progress * 100).rounded())) percent"))
                        .accessibilityIdentifier("player.progress")
                    if let counter {
                        Text(counter).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                            .monospacedDigit()
                    }
                }
                if let title {
                    Text(title).dsFont(Tokens.TypeScale.uiCallout).fontWeight(.semibold)
                        .foregroundStyle(Color.ds.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .accessibilityIdentifier("assessment.section")
                }
            }
            .padding(.horizontal, Tokens.Space.l)
            .padding(.vertical, Tokens.Space.s)
            Divider()
            if let host, let payload {
                ExerciseHostView(
                    host: host, payload: payload, bundle: bundle, services: services, onContinue: onContinue
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .id(position)
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Color.ds.background)
        .autoAnswerBar(debug, host: host, advance: onContinue)
    }
}

/// The calm page around an assessment's intro or result: Moka, a title, a column of text, then the buttons.
struct AssessmentPage<Content: View, Buttons: View>: View {
    let pose: Mascot.Pose
    let title: String
    let identifier: String
    @ViewBuilder let content: () -> Content
    @ViewBuilder let buttons: () -> Buttons

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                    Mascot(pose: pose, size: 120, decorative: true)
                        .frame(maxWidth: .infinity)
                        .padding(.top, Tokens.Space.xxl)
                    Text(title).dsFont(Tokens.TypeScale.screenTitle).foregroundStyle(Color.ds.ink)
                        .accessibilityAddTraits(.isHeader)
                    content()
                }
                .readableColumn()
                .padding(.bottom, Tokens.Space.xxl)
            }
            VStack(spacing: Tokens.Space.m) { buttons() }
                .readableColumn()
                .padding(.vertical, Tokens.Space.l)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.ds.background)
        .accessibilityIdentifier(identifier)
    }
}
