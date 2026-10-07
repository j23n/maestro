import LearningCore
import SwiftUI

/// Real-world texts drawn natively from their layout (docs/06 §4): one view per layout type, sharing the card
/// styling, so every Italian word can be tapped for English and read by VoiceOver. Strings the author listed in
/// `ignore`, prices and times arrive as plain strings and aren't tappable.
struct RealWorldLayoutView: View {
    let layout: LayoutPayload
    /// (1-based string number in reading order, token index)
    let onTap: (Int, Int) -> Void
    private let numbers: [LayoutString: Int]

    init(layout: LayoutPayload, onTap: @escaping (Int, Int) -> Void) {
        self.layout = layout
        self.onTap = onTap
        numbers = layout.stringNumbers
    }

    var body: some View {
        content
            .padding(Tokens.Space.xl)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: Tokens.Radius.card).fill(background))
            .overlay(RoundedRectangle(cornerRadius: Tokens.Radius.card)
                .strokeBorder(border, lineWidth: Tokens.Border.hairline))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("reading.layout")
    }

    @ViewBuilder private var content: some View {
        switch layout {
        case .menu(let title, let sections):
            VStack(alignment: .leading, spacing: Tokens.Space.l) {
                heading(title)
                ForEach(Array(sections.enumerated()), id: \.offset) { _, section in
                    VStack(alignment: .leading, spacing: Tokens.Space.s) {
                        string(section.title, style: Tokens.TypeScale.sectionTitle)
                        ForEach(Array(section.rows.enumerated()), id: \.offset) { _, row in
                            VStack(alignment: .leading, spacing: Tokens.Space.xxs) {
                                HStack(alignment: .firstTextBaseline) {
                                    string(row.name)
                                    dots
                                    string(row.price)
                                }
                                if let note = row.note { string(note, style: Tokens.TypeScale.uiCaption) }
                            }
                        }
                    }
                }
            }
        case .receipt(let shop, let rows, let total, let footer):
            VStack(alignment: .leading, spacing: Tokens.Space.s) {
                heading(shop).frame(maxWidth: .infinity)
                dashed
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    HStack(alignment: .firstTextBaseline) {
                        if let qty = row.qty { string(qty) }
                        string(row.name)
                        Spacer()
                        string(row.price)
                    }
                }
                dashed
                HStack { string(total, style: Tokens.TypeScale.rowTitle) }
                if let footer { string(footer, style: Tokens.TypeScale.uiCaption).frame(maxWidth: .infinity) }
            }
            .fontDesign(.monospaced)
        case .sign(let lines, _):
            VStack(spacing: Tokens.Space.s) {
                ForEach(Array(lines.enumerated()), id: \.offset) { n, line in
                    string(line, style: n == 0 ? Tokens.TypeScale.screenTitle : Tokens.TypeScale.italianBody)
                }
            }
            .frame(maxWidth: .infinity)
            .multilineTextAlignment(.center)
        case .hours(let title, let rows, let note):
            VStack(alignment: .leading, spacing: Tokens.Space.s) {
                heading(title)
                Grid(alignment: .leading, horizontalSpacing: Tokens.Space.l, verticalSpacing: Tokens.Space.s) {
                    ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                        GridRow {
                            string(row.days)
                            string(row.times)
                        }
                    }
                }
                if let note { string(note, style: Tokens.TypeScale.uiCaption) }
            }
        case .timetable(let title, let columns, let rows):
            VStack(alignment: .leading, spacing: Tokens.Space.m) {
                heading(title)
                ScrollView(.horizontal) {
                    Grid(alignment: .leading, horizontalSpacing: Tokens.Space.l, verticalSpacing: Tokens.Space.s) {
                        GridRow {
                            ForEach(Array(columns.enumerated()), id: \.offset) { _, c in
                                string(c, style: Tokens.TypeScale.uiCaption)
                            }
                        }
                        Divider()
                        ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                            GridRow {
                                ForEach(Array(row.enumerated()), id: \.offset) { _, cell in string(cell) }
                            }
                        }
                    }
                }
            }
        case .fields(_, let title, let fields):
            VStack(alignment: .leading, spacing: Tokens.Space.m) {
                heading(title)
                ForEach(Array(fields.enumerated()), id: \.offset) { _, field in
                    VStack(alignment: .leading, spacing: Tokens.Space.xxs) {
                        string(field.label, style: Tokens.TypeScale.uiCaption)
                        string(field.value)
                    }
                }
            }
        case .ad(let title, let body, let contact):
            VStack(alignment: .leading, spacing: Tokens.Space.m) {
                heading(title)
                ForEach(Array(body.enumerated()), id: \.offset) { _, line in string(line) }
                if let contact { string(contact, style: Tokens.TypeScale.rowTitle) }
            }
        case .message(let from, let time, let bubbles):
            VStack(alignment: .leading, spacing: Tokens.Space.s) {
                HStack {
                    string(from, style: Tokens.TypeScale.rowTitle)
                    Spacer()
                    if let time { string(time, style: Tokens.TypeScale.uiCaption) }
                }
                ForEach(Array(bubbles.enumerated()), id: \.offset) { _, bubble in
                    string(bubble)
                        .padding(Tokens.Space.m)
                        .background(RoundedRectangle(cornerRadius: Tokens.Radius.tile).fill(Color.ds.subtle))
                }
            }
        case .postcard(let greeting, let body, let closing, let signature, let address):
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: Tokens.Space.xxl) {
                    postcardText(greeting, body, closing, signature)
                    if let address { postcardAddress(address).frame(width: 200) }
                }
                VStack(alignment: .leading, spacing: Tokens.Space.l) {
                    postcardText(greeting, body, closing, signature)
                    if let address { postcardAddress(address) }
                }
            }
        case .list(let title, let items):
            VStack(alignment: .leading, spacing: Tokens.Space.s) {
                if let title { heading(title) }
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    HStack(alignment: .firstTextBaseline, spacing: Tokens.Space.s) {
                        Text("•").foregroundStyle(Color.ds.secondary).accessibilityHidden(true)
                        string(item)
                    }
                }
            }
        }
    }

    private func postcardText(_ greeting: LayoutString, _ body: [LayoutString], _ closing: LayoutString,
                              _ signature: LayoutString) -> some View
    {
        VStack(alignment: .leading, spacing: Tokens.Space.s) {
            string(greeting)
            ForEach(Array(body.enumerated()), id: \.offset) { _, line in string(line) }
            string(closing)
            string(signature, style: Tokens.TypeScale.rowTitle)
        }
    }

    private func postcardAddress(_ lines: [LayoutString]) -> some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xs) {
            ForEach(Array(lines.enumerated()), id: \.offset) { _, line in string(line) }
        }
        .padding(.leading, Tokens.Space.l)
        .overlay(alignment: .leading) { Rectangle().fill(Color.ds.divider).frame(width: Tokens.Border.hairline) }
    }

    private func heading(_ s: LayoutString) -> some View {
        string(s, style: Tokens.TypeScale.rowTitle).accessibilityAddTraits(.isHeader)
    }

    @ViewBuilder private func string(_ s: LayoutString, style: TypeStyle = Tokens.TypeScale.italianBody)
        -> some View
    {
        let n = numbers[s] ?? 0
        switch s {
        case .italian(let t):
            TokenText(text: t, line: n, style: style, onTap: { onTap(n, $0) })
                .accessibilityIdentifier("reading.field.\(n)")
        case .plain(let p):
            Text(p).dsFont(style).foregroundStyle(Color.ds.ink)
                .accessibilityIdentifier("reading.field.\(n)")
        }
    }

    private var dots: some View {
        Rectangle().fill(Color.clear).frame(height: 1)
            .overlay(Line().stroke(Color.ds.divider, style: StrokeStyle(lineWidth: 1, dash: [2, 3])))
            .frame(maxWidth: .infinity)
            .accessibilityHidden(true)
    }

    private var dashed: some View {
        Line().stroke(Color.ds.divider, style: StrokeStyle(lineWidth: 1, dash: [4, 3])).frame(height: 1)
            .accessibilityHidden(true)
    }

    private var background: Color {
        if case .sign(_, let style) = layout, style == "warning" || style == "closed" {
            return Color.ds.warningBackground
        }
        return Color.ds.background
    }

    private var border: Color {
        if case .sign(_, let style) = layout, style == "warning" || style == "closed" { return Color.ds.warning }
        return Color.ds.divider
    }
}

/// A horizontal rule as a shape, for dotted and dashed leaders.
private struct Line: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: rect.minX, y: rect.midY))
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
        return p
    }
}
