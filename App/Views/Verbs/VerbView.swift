import SwiftUI
import ItalianCore
import GrammarKit
import LexiconKit

/// A verb page (HANDOFF.md 3.3): badges, participle and gerund, the form the learner came from,
/// mood tabs and tense blocks, irregular forms in bold orange. Wide layouts show every mood at once.
struct VerbView: View {
    let lemmaID: String
    let highlightTag: String?

    @Environment(AppModel.self) private var model
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var mood: Mood = .ind

    private static let moods: [Mood] = [.ind, .sub, .cond, .imp]

    var body: some View {
        if let table = model.conjugator?.table(for: lemmaID), let entry = model.content?.entry(lemmaID) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header(entry, table: table)
                    if let tag = highlightTag.flatMap(FormTag.init), let form = table.form(for: tag) ?? compoundForm(table, tag) {
                        banner(tag: tag, form: form, entry: entry)
                    }
                    if sizeClass == .regular {
                        ForEach(Self.moods, id: \.self) { m in
                            moodSection(m, table: table)
                        }
                    } else {
                        Picker("Mood", selection: $mood) {
                            ForEach(Self.moods, id: \.self) { m in Text(m.italianName.capitalized).tag(m) }
                        }
                        .pickerStyle(.segmented)
                        moodSection(mood, table: table, showTitle: false)
                    }
                }
                .padding(20)
                .frame(maxWidth: 1000, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
            .navigationTitle(entry.headword)
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .onAppear {
                if let tag = highlightTag.flatMap(FormTag.init), Self.moods.contains(tag.mood) { mood = tag.mood }
            }
        } else {
            EmptyState(title: "No table for this verb", message: LemmaID.headword(of: lemmaID), systemImage: "tablecells")
        }
    }

    private func compoundForm(_ table: ConjugationTable, _ tag: FormTag) -> ConjugatedForm? {
        var plain = tag
        plain.auxiliary = nil
        return table.form(for: plain)
    }

    private func header(_ entry: Entry, table: ConjugationTable) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(italian: entry.headword).font(.system(size: 32, weight: .bold, design: .serif))
                Button {
                    model.speech.say(entry.headword)
                } label: {
                    Image(systemName: "speaker.wave.2.fill").frame(width: 44, height: 44)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("Play \(entry.headword)")
            }
            if let gloss = entry.senses.first(where: { !$0.retired })?.gloss {
                Text(gloss).font(.title3)
            }
            HStack(spacing: 6) {
                if table.isIrregular { Tag(text: "irregular", colors: Theme.irregularBadge) }
                if let aux = table.auxiliary {
                    Tag(text: aux == "both" ? "essere or avere" : "with \(aux)", colors: Theme.kind(.word))
                }
                Tag(text: group(entry.headword), colors: Theme.kind(.word))
            }
            HStack(spacing: 16) {
                if let p = table.participle { labeled("participio", p) }
                if let g = table.gerund { labeled("gerundio", g) }
            }
            .padding(.top, 2)
            NavigationLink(value: Route.entry(entry.id)) {
                Label("In dictionary", systemImage: "character.book.closed")
            }
            .font(.subheadline)
        }
    }

    private func labeled(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            Text(italian: value).font(.system(.body, design: .serif))
        }
    }

    private func group(_ infinitive: String) -> String {
        if infinitive.hasSuffix("are") { return "-are" }
        if infinitive.hasSuffix("ere") || infinitive.hasSuffix("rre") { return "-ere" }
        if infinitive.hasSuffix("ire") { return "-ire" }
        return "verb"
    }

    private func banner(tag: FormTag, form: ConjugatedForm, entry: Entry) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(italian: form.text).font(.system(.title3, design: .serif).weight(.semibold))
                    Text(tag.label).font(.subheadline)
                }
                Spacer()
            }
            let item = RememberItem.verbForm(lemmaID: entry.id, formTag: tag.description, surface: form.text)
            let text = item.rowText(model: model)
            RememberRow(item: item, title: text.title, detail: text.detail)
        }
        .padding(12)
        .background(Theme.info.background, in: RoundedRectangle(cornerRadius: 12))
    }

    private func moodSection(_ mood: Mood, table: ConjugationTable, showTitle: Bool = true) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if showTitle { SectionLabel(mood.italianName) }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 12, alignment: .top)], alignment: .leading,
                      spacing: 12) {
                ForEach(table.blocks(for: mood)) { block in
                    TenseBlockView(block: block, highlight: highlightTag.flatMap(FormTag.init))
                }
            }
        }
    }
}

struct TenseBlockView: View {
    let block: TenseBlock
    let highlight: FormTag?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(block.title.capitalized).font(.subheadline.weight(.semibold))
            ForEach(block.forms) { form in
                let isHighlighted = highlight.map { $0.mood == form.tag.mood && $0.tense == form.tag.tense && $0.person == form.tag.person } ?? false
                HStack(spacing: 8) {
                    Text(form.tag.person?.pronoun ?? "")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .frame(width: 58, alignment: .leading)
                    Text(italian: form.text)
                        .font(.system(.body, design: .serif).weight(form.isIrregular ? .bold : .regular))
                        .foregroundStyle(form.isIrregular ? Theme.irregularForm : Theme.ink)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(isHighlighted ? Theme.selectionFill : Color.clear, in: RoundedRectangle(cornerRadius: 6))
                .accessibilityElement(children: .combine)
                .accessibilityHint(form.isIrregular ? "irregular" : "")
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 14))
    }
}
