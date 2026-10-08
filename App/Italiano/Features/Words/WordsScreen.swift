import LearningCore
import SwiftUI

/// "Your words" (`Words.png`): title and count, search (Italian or English, accents optional), filter chips with
/// counts, then a table on regular width (word, meaning, four skill bars, next review) or rows on compact width.
struct WordsScreen: View {
    let app: AppModel
    @State private var query = ""
    @State private var filter: WordFilter = .all
    @Environment(\.isCompactWidth) private var isCompact

    var body: some View {
        let all = app.wordRows
        let counts = WordsCopy.counts(all)
        let shown = visible(all)
        ScrollView {
            VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                header(count: all.count)
                chips(counts)
                if shown.isEmpty {
                    Text(all.isEmpty ? "Words you meet in lessons appear here." : "No words match.")
                        .dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
                        .accessibilityIdentifier("words.empty")
                } else if isCompact {
                    compactList(shown)
                } else {
                    table(shown)
                }
                Text(
                    "Each bar shows how likely you are to remember the word in that skill. "
                        + "Strength grows every time you get it right after a gap."
                )
                .dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
            }
            .readableColumn(maxWidth: 1100)
            .padding(.vertical, Tokens.Space.xxl)
        }
        .background(Color.ds.background)
        .searchable(text: $query, prompt: "Italian or English")
    }

    private func visible(_ rows: [WordRow]) -> [WordRow] {
        let filtered = rows.filter(filter.matches)
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return filtered }
        let folded = q.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
        return filtered.filter {
            $0.display.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil).contains(folded)
                || $0.gloss.localizedCaseInsensitiveContains(q)
        }
    }

    private func header(count: Int) -> some View {
        VStack(alignment: .leading, spacing: Tokens.Space.s) {
            Text("Your words").dsFont(Tokens.TypeScale.display).foregroundStyle(Color.ds.ink)
                .accessibilityAddTraits(.isHeader)
            Text(WordsCopy.subtitle(count: count)).dsFont(Tokens.TypeScale.uiCallout)
                .foregroundStyle(Color.ds.secondary)
        }
    }

    private func chips(_ counts: [WordFilter: Int]) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Tokens.Space.s) {
                ForEach(WordFilter.allCases, id: \.self) { f in
                    let selected = f == filter
                    Button {
                        filter = f
                    } label: {
                        Text("\(f.title) \(counts[f] ?? 0)")
                            .dsFont(Tokens.TypeScale.uiCallout)
                            .foregroundStyle(selected ? Color.ds.background : Color.ds.ink)
                            .padding(.horizontal, Tokens.Space.l)
                            .frame(minHeight: Tokens.Size.minTouch)
                            .background(Capsule().fill(selected ? Color.ds.ink : Color.clear))
                            .overlay(
                                Capsule().strokeBorder(
                                    selected ? Color.clear : Color.ds.divider,
                                    lineWidth: Tokens.Border.control))
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(selected ? .isSelected : [])
                    .accessibilityIdentifier("words.filter.\(f.rawValue)")
                }
            }
        }
    }

    private func table(_ rows: [WordRow]) -> some View {
        Card {
            Grid(alignment: .leading, horizontalSpacing: Tokens.Space.xl, verticalSpacing: 0) {
                GridRow {
                    ForEach(
                        ["Word", "Meaning", "Reading", "Listening", "Recall", "Speaking", "Next review"], id: \.self
                    ) {
                        Text($0).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                    }
                }
                .padding(.bottom, Tokens.Space.m)
                ForEach(rows) { row in
                    Divider().gridCellUnsizedAxes(.horizontal)
                    GridRow {
                        ItalianText(row.display, style: Tokens.TypeScale.rowTitle)
                        Text(row.gloss).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
                        ForEach(0..<4, id: \.self) { i in bars(row.bars[i]) }
                        nextReview(row)
                    }
                    .padding(.vertical, Tokens.Space.l)
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("words.row.\(row.id.rawValue)")
                }
            }
        }
    }

    private func compactList(_ rows: [WordRow]) -> some View {
        VStack(spacing: 0) {
            ForEach(rows) { row in
                VStack(alignment: .leading, spacing: Tokens.Space.s) {
                    HStack(alignment: .firstTextBaseline) {
                        ItalianText(row.display, style: Tokens.TypeScale.rowTitle)
                        Spacer()
                        nextReview(row)
                    }
                    Text(row.gloss).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                    SkillBars(levels: row.bars.map { $0 ?? 0 }, labels: ["Read", "Listen", "Recall", "Speak"])
                }
                .padding(.vertical, Tokens.Space.l)
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("words.row.\(row.id.rawValue)")
                Divider()
            }
        }
    }

    @ViewBuilder private func bars(_ level: Int?) -> some View {
        if let level {
            HStack(spacing: 3) {
                ForEach(0..<4, id: \.self) { i in
                    RoundedRectangle(cornerRadius: 2)
                        .fill(i < level ? Color.ds.accent : Color.ds.subtle)
                        .frame(width: 20, height: 6)
                }
            }
            .accessibilityElement()
            .accessibilityLabel(Text("\(level) of 4"))
        } else {
            Text("—").foregroundStyle(Color.ds.secondary).accessibilityLabel(Text("not practised"))
        }
    }

    private func nextReview(_ row: WordRow) -> some View {
        Text(row.nextReview ?? "Not yet")
            .dsFont(Tokens.TypeScale.uiCallout)
            .fontWeight(row.isDueToday ? .semibold : .regular)
            .foregroundStyle(row.isDueToday ? Color.ds.accent : Color.ds.secondary)
    }
}
