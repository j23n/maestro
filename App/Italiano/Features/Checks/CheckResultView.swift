import SwiftUI

/// The unit check result (docs/06 § 18): passed or not yet, the overall score, each section's score, the words that
/// come back first in reviews, then Done and Retake.
struct CheckResultView: View {
    let content: CheckResultContent
    let onDone: () -> Void
    let onRetake: () -> Void

    var body: some View {
        ScrollView {
            VStack(spacing: Tokens.Space.xxl) {
                Mascot(pose: content.passed ? .cheer : .think, size: 120, decorative: true)
                VStack(spacing: Tokens.Space.s) {
                    Text(content.overall).dsFont(Tokens.TypeScale.celebration).foregroundStyle(Color.ds.ink)
                        .accessibilityIdentifier("check.overall")
                    Text(content.headline).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
                        .multilineTextAlignment(.center)
                }
                Card {
                    ForEach(Array(content.sections.enumerated()), id: \.offset) { n, s in
                        if n > 0 { CardDivider() }
                        VStack(alignment: .leading, spacing: Tokens.Space.s) {
                            HStack {
                                Text(s.title).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                                Spacer()
                                Text(s.score).dsFont(Tokens.TypeScale.uiBody).fontWeight(.semibold)
                                    .foregroundStyle(Color.ds.ink)
                            }
                            DSProgressBar(value: s.fraction)
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("check.section.\(n)")
                    }
                }
                if !content.practise.isEmpty {
                    VStack(alignment: .leading, spacing: Tokens.Space.s) {
                        Text("These come back first in your reviews").dsFont(Tokens.TypeScale.uiCallout)
                            .foregroundStyle(Color.ds.secondary)
                        ItalianText(
                            content.practise.joined(separator: ", "), style: Tokens.TypeScale.translation,
                            italic: true)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityIdentifier("check.practise")
                }
                Button("Done", action: onDone)
                    .buttonStyle(.dsPrimary)
                    .keyboardShortcut(.return, modifiers: [])
                    .accessibilityIdentifier("check.done")
                Button(content.passed ? "Take it again" : "Retake the check", action: onRetake)
                    .buttonStyle(.dsSecondary)
                    .accessibilityIdentifier("check.retake")
            }
            .readableColumn()
            .padding(.vertical, Tokens.Space.xxl)
        }
        .background(Color.ds.background)
    }
}
