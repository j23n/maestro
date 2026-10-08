import SwiftUI

/// The stepped-feedback panel (docs/06 § Shared player behaviour, `TryAgain.png`): `warningBackground`, radius 14,
/// padding 16; Moka (think, 56) on the left; a short headline (600, `warningText`); the body in Literata italic;
/// buttons below. Success uses the success colour and no mascot unless a note is shown. All feedback text is
/// announced to VoiceOver. Slides up from the bottom (cross-fades with Reduce Motion).
struct FeedbackPanel<Buttons: View>: View {
    typealias Tone = FeedbackTone

    let tone: Tone
    let headline: String
    var detail: String?
    var showsMascot = true
    @ViewBuilder var buttons: Buttons

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.l) {
            HStack(alignment: .top, spacing: Tokens.Space.l) {
                if showsMascot && tone != .success {
                    Mascot(pose: .think, size: 56, decorative: true, isHint: true)
                }
                VStack(alignment: .leading, spacing: Tokens.Space.s) {
                    Text(headline)
                        .dsFont(Tokens.TypeScale.uiTitle)
                        .foregroundStyle(tone == .success ? Color.ds.success : Color.ds.warningText)
                    if let detail {
                        MixedText(text: detail, style: Tokens.TypeScale.uiBody)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(Tokens.Space.l)
            .background(
                RoundedRectangle(cornerRadius: Tokens.Radius.tile)
                    .fill(tone == .success ? Color.ds.accentTint : Color.ds.warningBackground)
            )
            .accessibilityElement(children: .combine)
            buttons
        }
        .accessibilityIdentifier("feedback.panel")
        .onAppear {
            AccessibilityNotification.Announcement([headline, detail].compactMap { $0 }.joined(separator: ". ")).post()
        }
    }
}

/// Outside the generic panel so every specialisation shares one type.
enum FeedbackTone: Sendable, Equatable { case success, hint, answer }

extension AnyTransition {
    /// docs/07 § Accessibility: no sliding panels with Reduce Motion.
    static func feedbackPanel(reduceMotion: Bool) -> AnyTransition {
        reduceMotion ? .opacity : .move(edge: .bottom).combined(with: .opacity)
    }
}
