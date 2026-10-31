import SwiftUI
import GrammarKit
import ItalianCore
import LexiconKit
import PackKit

/// A grammar page (HANDOFF.md 3.3): when it's used, how it's formed, irregulars, examples from
/// the learner's own texts, and Remember.
struct GrammarTopicView: View {
    let topicID: String
    @Environment(AppModel.self) private var model

    var body: some View {
        if let topic = model.grammarTopic(topicID) {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        LevelTag(level: topic.level)
                        Spacer()
                    }
                    Text(topic.title).font(.system(size: 30, weight: .bold))
                    Text(markdown: topic.summary).font(.title3).foregroundStyle(.secondary)
                    RememberRow(item: rememberItem(topic), title: topic.title, detail: nil)
                    ForEach(Array(MarkdownBlock.parse(topic.body).enumerated()), id: \.offset) { _, block in
                        MarkdownBlockView(block: block)
                    }
                    let examples = examplesInTexts
                    if !examples.isEmpty {
                        SectionLabel("In your texts").padding(.top, 8)
                        ForEach(examples, id: \.id) { ex in
                            NavigationLink(value: Route.text(ex.textID)) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(ex.attributed).font(.system(.body, design: .serif))
                                    Text(ex.textTitle).font(.caption).foregroundStyle(.secondary)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(12)
                                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .padding(20)
                .frame(maxWidth: 760, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
            .navigationTitle(topic.title)
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
        } else {
            EmptyState(title: "Topic not found", message: topicID, systemImage: "text.book.closed")
        }
    }

    struct Example {
        let id: String
        let textID: String
        let textTitle: String
        let sentence: Sentence
        let ranges: [UTF16Range]

        var attributed: AttributedString {
            var a = AttributedString(sentence.text)
            a.languageIdentifier = "it-IT"
            for r in ranges {
                if let range = Range(NSRange(location: r.start, length: r.length), in: a) {
                    a[range].inlinePresentationIntent = .stronglyEmphasized
                }
            }
            return a
        }
    }

    /// Sentences in the library that use this topic, the item in bold. Find all in my texts.
    private var examplesInTexts: [Example] {
        var out: [Example] = []
        for entry in model.entries {
            guard let text = model.text(entry.id) else { continue }
            for sentence in text.sentences {
                var ranges: [UTF16Range] = []
                for unit in sentence.units ?? [] where unit.grammar?.contains(topicID) == true {
                    ranges += unit.tokens.compactMap { sentence.tokens.indices.contains($0) ? sentence.tokens[$0].r : nil }
                }
                for token in sentence.tokens where token.grammar?.contains(topicID) == true {
                    ranges.append(token.r)
                }
                if !ranges.isEmpty {
                    out.append(Example(id: "\(text.id)#\(sentence.id)", textID: text.id, textTitle: text.title,
                                       sentence: sentence, ranges: ranges))
                }
                if out.count >= 12 { return out }
            }
        }
        return out
    }

    private func rememberItem(_ topic: GrammarTopicRow) -> RememberItem {
        let item = RememberItem.grammar(topic.id, surface: topic.title)
        if let ex = examplesInTexts.first {
            return item.inSentence(textID: ex.textID, sentenceID: ex.sentence.id, text: ex.sentence.text,
                                   translation: ex.sentence.translation, ranges: ex.ranges)
        }
        return item
    }
}

struct MarkdownBlockView: View {
    let block: MarkdownBlock

    var body: some View {
        switch block {
        case .heading(let title):
            Text(title).font(.headline).padding(.top, 8)
        case .paragraph(let text):
            Text(markdown: text).fixedSize(horizontal: false, vertical: true)
        case .list(let items):
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("•").foregroundStyle(.secondary)
                        Text(markdown: item).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        case .table(let header, let rows):
            ScrollView(.horizontal, showsIndicators: false) {
                Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                    GridRow {
                        ForEach(Array(header.enumerated()), id: \.offset) { _, cell in
                            Text(markdown: cell).font(.footnote.weight(.semibold)).foregroundStyle(.secondary)
                        }
                    }
                    Divider()
                    ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                        GridRow {
                            ForEach(Array(row.enumerated()), id: \.offset) { i, cell in
                                Text(markdown: cell)
                                    .font(i == 0 ? .footnote : .system(.callout, design: .serif))
                                    .foregroundStyle(i == 0 ? Color.secondary : Color.primary)
                            }
                        }
                    }
                }
                .padding(12)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12))
            }
        }
    }
}
