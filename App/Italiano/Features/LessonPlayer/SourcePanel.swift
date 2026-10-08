import LearningCore
import SwiftUI

/// Draws a `SourceText`: one story line, a whole text, or a real-world layout such as the bar's menu, tappable for
/// glosses like everywhere else.
struct SourcePanel: View {
    let source: SourceText
    var onGloss: (TextID, Int, Int, ItemID?) -> Void = { _, _, _, _ in }

    var body: some View {
        if let layout = source.text.layout, source.line == nil {
            RealWorldLayoutView(layout: layout, onTap: { onGloss(source.text.id, $0, $1, nil) })
        } else {
            Card {
                VStack(alignment: .leading, spacing: Tokens.Space.s) {
                    ForEach(lines, id: \.number) { line in
                        TokenText(
                            text: line.text, line: line.number,
                            onTap: { token in
                                onGloss(source.text.id, line.number, token, line.text.tokens[safe: token]?.itemId)
                            })
                    }
                }
            }
            .accessibilityIdentifier("exercise.source")
        }
    }

    private var lines: [PlayerLine] {
        guard let n = source.line else { return source.text.lines }
        return source.text.lines.filter { $0.number == n }
    }
}
