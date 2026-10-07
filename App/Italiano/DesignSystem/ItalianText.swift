import SwiftUI

/// All Italian on screen goes through this view (CLAUDE.md, docs/06 § Shared player behaviour): Literata, and the
/// attributed string's speech language set to it-IT so VoiceOver reads it with the Italian voice. Never put
/// `lineLimit` on Italian. Inline `*…*` marks Italian inside English and `**…**` highlights a target form (docs/06 §5).
struct ItalianText: View {
    let text: String
    var style: TypeStyle = Tokens.TypeScale.italianBody
    var italic = false
    var highlight: Color = Color.ds.accent

    init(_ text: String, style: TypeStyle = Tokens.TypeScale.italianBody, italic: Bool = false) {
        self.text = text
        self.style = style
        self.italic = italic
    }

    var body: some View {
        Text(Self.attributed(text, highlight: highlight))
            .dsFont(style)
            .italic(italic)
            .foregroundStyle(Color.ds.ink)
            .fixedSize(horizontal: false, vertical: true)
    }

    /// `**x**` → semibold accent; the whole string is tagged it-IT for speech.
    static func attributed(_ source: String, highlight: Color) -> AttributedString {
        var result = AttributedString()
        var rest = Substring(source)
        while let open = rest.range(of: "**") {
            result += AttributedString(String(rest[..<open.lowerBound]))
            let after = rest[open.upperBound...]
            guard let close = after.range(of: "**") else {
                result += AttributedString(String(rest[open.lowerBound...]))
                rest = ""
                break
            }
            var strong = AttributedString(String(after[..<close.lowerBound]))
            strong.foregroundColor = highlight
            strong.inlinePresentationIntent = .stronglyEmphasized
            result += strong
            rest = after[close.upperBound...]
        }
        result += AttributedString(String(rest))
        result.accessibilitySpeechLanguage = "it-IT"
        return result
    }
}

/// English prose with inline Italian (`*vorrei*`): the Italian runs are Literata italic and spoken in Italian.
struct MixedText: View {
    let text: String
    var style: TypeStyle = Tokens.TypeScale.uiBody

    var body: some View {
        Text(Self.attributed(text))
            .dsFont(style)
            .foregroundStyle(Color.ds.ink)
            .fixedSize(horizontal: false, vertical: true)
    }

    /// Splits on `**` (highlight) before `*` (Italian), so `*un **caffè***` works too.
    static func attributed(_ source: String) -> AttributedString {
        var result = AttributedString()
        var italian = false
        var strong = false
        var buffer = ""
        func flush() {
            guard !buffer.isEmpty else { return }
            var run = AttributedString(buffer)
            if italian {
                run.font = .ds(Tokens.TypeScale.translation)
                run.accessibilitySpeechLanguage = "it-IT"
            }
            if strong {
                run.foregroundColor = Color.ds.accent
                run.inlinePresentationIntent = .stronglyEmphasized
            }
            result += run
            buffer = ""
        }
        var chars = Substring(source)
        while let c = chars.first {
            if chars.hasPrefix("**") {
                flush()
                strong.toggle()
                chars = chars.dropFirst(2)
            } else if c == "*" {
                flush()
                italian.toggle()
                chars = chars.dropFirst()
            } else {
                buffer.append(c)
                chars = chars.dropFirst()
            }
        }
        flush()
        return result
    }
}
