import LearningCore
import SwiftUI

/// An annotated Italian string with every word tappable for its gloss (docs/06 §2). Words are links inside one
/// `Text`, so lines wrap like prose; names, numbers and punctuation aren't links. The read-along token gets the
/// accent tint, the selected one the accent colour, new words a dotted accent underline, and note examples their
/// target forms in semibold accent. The whole string is spoken in Italian by VoiceOver.
struct TokenText: View {
    let text: TokenizedText
    var line = 0
    var style: TypeStyle = Tokens.TypeScale.italianBody
    /// The token being read aloud (read-along).
    var current: Int?
    var selected: Int?
    var marksNewWords = false
    var highlight: Set<Int> = []
    var onTap: ((Int) -> Void)?

    var body: some View {
        Text(attributed)
            .dsFont(style)
            .foregroundStyle(Color.ds.ink)
            .tint(Color.ds.ink)
            .fixedSize(horizontal: false, vertical: true)
            .environment(
                \.openURL,
                OpenURLAction { url in
                    guard url.scheme == Self.scheme, let i = Int(url.lastPathComponent) else { return .systemAction }
                    onTap?(i)
                    return .handled
                })
    }

    static let scheme = "italiano-gloss"
    /// Bit 1 of `tokens.flags`: new in this text (docs/03).
    static let newFlag = 1

    var attributed: AttributedString {
        var out = AttributedString(text.lead)
        for (i, token) in text.tokens.enumerated() {
            var run = AttributedString(token.surface)
            if token.kind == .word, onTap != nil {
                run.link = URL(string: "\(Self.scheme)://\(line)/\(i)")
            }
            if i == current { run.backgroundColor = Color.ds.accentTint }
            if i == selected { run.foregroundColor = Color.ds.accent }
            if highlight.contains(i) {
                run.foregroundColor = Color.ds.accent
                run.inlinePresentationIntent = .stronglyEmphasized
            }
            if marksNewWords, token.flags & Self.newFlag != 0 {
                run.underlineStyle = Text.LineStyle(pattern: .dot, color: Color.ds.accent)
            }
            out += run
            out += AttributedString(token.trailing)
        }
        out.accessibilitySpeechLanguage = "it-IT"
        return out
    }
}
