import Foundation

/// The small Markdown subset grammar topics use (content/grammar/*.md): "## " headings,
/// paragraphs, "- " lists and pipe tables. Inline markup (*italic*, **bold**) is left in the text
/// for the app to render.
public enum MarkdownBlock: Sendable, Hashable {
    case heading(String)
    case paragraph(String)
    case list([String])
    case table(header: [String], rows: [[String]])

    public static func parse(_ markdown: String) -> [MarkdownBlock] {
        var blocks: [MarkdownBlock] = []
        var paragraph: [String] = []
        var list: [String] = []
        var table: [[String]] = []

        func flush() {
            if !paragraph.isEmpty { blocks.append(.paragraph(paragraph.joined(separator: " "))) }
            if !list.isEmpty { blocks.append(.list(list)) }
            if let header = table.first {
                blocks.append(.table(header: header, rows: Array(table.dropFirst())))
            }
            paragraph = []
            list = []
            table = []
        }

        for raw in markdown.components(separatedBy: "\n") {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.isEmpty {
                flush()
            } else if line.hasPrefix("#") {
                flush()
                let title = line.drop(while: { $0 == "#" }).trimmingCharacters(in: .whitespaces)
                blocks.append(.heading(title))
            } else if line.hasPrefix("|") {
                if !paragraph.isEmpty || !list.isEmpty {
                    let pending = table
                    table = []
                    flush()
                    table = pending
                }
                let cells = line.trimmingCharacters(in: CharacterSet(charactersIn: "|"))
                    .components(separatedBy: "|")
                    .map { $0.trimmingCharacters(in: .whitespaces) }
                // Skip the separator row: | --- | --- |
                if cells.allSatisfy({ !$0.isEmpty && $0.allSatisfy { $0 == "-" || $0 == ":" } }) { continue }
                table.append(cells)
            } else if line.hasPrefix("- ") || line.hasPrefix("* ") {
                if !paragraph.isEmpty || !table.isEmpty { flush() }
                list.append(String(line.dropFirst(2)))
            } else {
                if !list.isEmpty || !table.isEmpty { flush() }
                paragraph.append(line)
            }
        }
        flush()
        return blocks
    }
}
