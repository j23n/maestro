// Renders the markdown subset the grammar reference pages actually use.
//
// `Text(LocalizedStringKey:)` handles inline emphasis and links but silently
// drops headings and tables — and several reference pages are mostly table,
// so they reach the screen as raw pipes. This splits a body into blocks and
// gives tables a Grid; everything else still goes through LocalizedStringKey
// so inline markdown keeps working.

import SwiftUI

enum MarkdownBlock {
    case heading(String, level: Int)
    case paragraph(String)
    case bullet(String)
    case table([[String]])

    static func parse(_ source: String) -> [MarkdownBlock] {
        var blocks: [MarkdownBlock] = []
        var paragraph: [String] = []

        // Source paragraphs are hard-wrapped; keeping those newlines would
        // reproduce the authoring width instead of reflowing to the screen.
        func flushParagraph() {
            let joined = paragraph.joined(separator: " ")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if !joined.isEmpty { blocks.append(.paragraph(joined)) }
            paragraph = []
        }

        var lines = source.components(separatedBy: .newlines)[...]
        while let line = lines.first {
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            if trimmed.hasPrefix("|") {
                flushParagraph()
                var rows: [[String]] = []
                while let row = lines.first,
                    row.trimmingCharacters(in: .whitespaces).hasPrefix("|")
                {
                    let cells = splitRow(row)
                    // The `|---|---|` separator carries no content.
                    if !cells.allSatisfy(isRule) { rows.append(cells) }
                    lines = lines.dropFirst()
                }
                // A table of entirely empty cells is a formatting artefact.
                if rows.contains(where: { $0.contains { !$0.isEmpty } }) {
                    blocks.append(.table(normalise(rows)))
                }
                continue
            }

            if trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ") {
                flushParagraph()
                blocks.append(.bullet(String(trimmed.dropFirst(2))))
            } else if trimmed.hasPrefix("#") {
                flushParagraph()
                let level = trimmed.prefix(while: { $0 == "#" }).count
                let text = trimmed.drop(while: { $0 == "#" })
                    .trimmingCharacters(in: .whitespaces)
                blocks.append(.heading(text, level: level))
            } else if trimmed.isEmpty {
                flushParagraph()
            } else {
                paragraph.append(trimmed)
            }
            lines = lines.dropFirst()
        }
        flushParagraph()
        return blocks
    }

    private static func splitRow(_ row: String) -> [String] {
        var cells = row.trimmingCharacters(in: .whitespaces)
            .split(separator: "|", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespaces) }
        // Leading and trailing pipes produce empty edge cells.
        if cells.first?.isEmpty == true { cells.removeFirst() }
        if cells.last?.isEmpty == true { cells.removeLast() }
        return cells
    }

    private static func isRule(_ cell: String) -> Bool {
        !cell.isEmpty && cell.allSatisfy { $0 == "-" || $0 == ":" }
    }

    /// Ragged rows would misalign the Grid.
    private static func normalise(_ rows: [[String]]) -> [[String]] {
        let width = rows.map(\.count).max() ?? 0
        return rows.map { $0 + Array(repeating: "", count: width - $0.count) }
    }
}

struct MarkdownBody: View {
    let markdown: String

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            ForEach(Array(MarkdownBlock.parse(markdown).enumerated()), id: \.offset) {
                _, block in
                switch block {
                case .heading(let text, let level):
                    Text(text)
                        .font(level <= 2 ? .title3 : .headline)
                        .fontDesign(.serif)
                        .foregroundStyle(Color.mCharcoal)
                        .padding(.top, 4)
                case .paragraph(let text):
                    Text(LocalizedStringKey(text))
                        .font(.callout)
                        .foregroundStyle(Color.mText)
                        .fixedSize(horizontal: false, vertical: true)
                case .bullet(let text):
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("•").foregroundStyle(Color.mTerracotta)
                        Text(LocalizedStringKey(text))
                            .font(.callout)
                            .foregroundStyle(Color.mText)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                case .table(let rows):
                    MarkdownTable(rows: rows)
                }
            }
        }
    }
}

/// Wide tables scroll rather than compressing the columns to unreadable.
struct MarkdownTable: View {
    let rows: [[String]]

    /// A first row of non-empty cells reads as a header; some pages ship an
    /// empty one purely to satisfy the separator syntax.
    private var hasHeader: Bool { rows.first?.contains { !$0.isEmpty } == true && rows.count > 1 }

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 7) {
                ForEach(rows.indices, id: \.self) { r in
                    GridRow {
                        ForEach(rows[r].indices, id: \.self) { c in
                            cell(rows[r][c], isHeader: hasHeader && r == 0)
                        }
                    }
                    if hasHeader && r == 0 {
                        Divider().gridCellColumns(rows[r].count)
                    }
                }
            }
            .padding(14)
        }
        .background(Color.mSurface, in: RoundedRectangle(cornerRadius: 8))
    }

    private func cell(_ text: String, isHeader: Bool) -> some View {
        Text(LocalizedStringKey(text))
            .font(.subheadline)
            .fontWeight(isHeader ? .semibold : .regular)
            .foregroundStyle(isHeader ? Color.mTextMuted : Color.mText)
    }
}
