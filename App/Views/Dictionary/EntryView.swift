import SwiftUI
import ItalianCore
import LexiconKit

/// A dictionary entry (HANDOFF.md 3.2): headword with article, IPA, gender, plural, numbered
/// senses with examples, "In your texts", source credit.
struct EntryView: View {
    let lemmaID: String
    @Environment(AppModel.self) private var model

    var body: some View {
        if let entry = model.content?.entry(lemmaID) {
            List {
                Section { header(entry) }
                    .listRowSeparator(.hidden)
                LabeledSection("Meanings") {
                    ForEach(Array(entry.senses.filter { !$0.retired }.enumerated()), id: \.element.id) { n, sense in
                        senseRow(n + 1, sense, entry: entry)
                    }
                }
                let texts = inYourTexts(entry)
                if !texts.isEmpty {
                    LabeledSection("In your texts") {
                        ForEach(texts) { t in
                            NavigationLink(value: Route.text(t.id)) {
                                HStack {
                                    Text(italian: t.title)
                                    Spacer()
                                    LevelTag(level: t.level)
                                }
                            }
                        }
                    }
                }
                Section {
                    Text("Entry from Wiktionary, CC BY-SA. Inflections also from Morph-it!.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .plainPage()
            .navigationTitle(entry.headword)
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
        } else {
            EmptyState(title: "Not in this dictionary", message: LemmaID.headword(of: lemmaID), systemImage: "questionmark.circle")
        }
    }

    private func header(_ entry: Entry) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(italian: entry.headwordWithArticle)
                    .font(.system(size: 32, weight: .semibold, design: .serif))
                Spacer(minLength: 8)
                if let first = entry.senses.first(where: { !$0.retired }) {
                    RememberButton(item: wordItem(first, entry: entry), title: entry.headword)
                }
            }
            HStack(spacing: 8) {
                if let ipa = entry.ipa?.trimmingCharacters(in: CharacterSet(charactersIn: "/[] ")), !ipa.isEmpty {
                    Text("/\(ipa)/").foregroundStyle(.secondary)
                }
                Tag(text: [PartOfSpeech.label(entry.pos), entry.genderLabel].compactMap { $0 }.joined(separator: " · "),
                    colors: Theme.kind(.word))
                if let plural = entry.plural, !plural.isEmpty {
                    HStack(spacing: 4) {
                        Text("plural").foregroundStyle(.secondary)
                        Text(italian: plural)
                    }
                }
                Spacer(minLength: 0)
                Button {
                    model.speech.say(entry.headword)
                } label: {
                    Image(systemName: "speaker.wave.2").frame(width: 44, height: 44)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("Play \(entry.headword)")
            }
            .font(.subheadline)
            if entry.pos == "v" {
                NavigationLink(value: Route.verb(lemmaID: entry.id, formTag: nil)) {
                    Label("Conjugation", systemImage: "tablecells")
                }
                .padding(.top, 2)
            }
        }
        .padding(.vertical, 4)
    }

    private func senseRow(_ number: Int, _ sense: Sense, entry: Entry) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text("\(number)").font(.subheadline.weight(.semibold)).monospacedDigit().foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 4) {
                Text(sense.gloss).font(.body.weight(.semibold))
                ForEach(sense.examples.prefix(2), id: \.italian) { ex in
                    VStack(alignment: .leading, spacing: 1) {
                        Text(italian: ex.italian).font(.system(.body, design: .serif)).italic()
                        if let en = ex.english { Text(en).font(.subheadline).foregroundStyle(.secondary) }
                    }
                }
            }
            Spacer(minLength: 8)
            if number > 1 {
                RememberButton(item: wordItem(sense, entry: entry), title: "\(entry.headword), \(sense.gloss)")
            }
        }
        .padding(.vertical, 4)
        .listRowSeparator(.hidden)
    }

    private func wordItem(_ sense: Sense, entry: Entry) -> RememberItem {
        let item = RememberItem.word(lemmaID: entry.id, senseID: sense.id, surface: entry.headword)
        if let ex = sense.examples.first {
            return item.inSentence(textID: "", sentenceID: "", text: ex.italian, translation: ex.english ?? "", ranges: [])
        }
        return item
    }

    private func inYourTexts(_ entry: Entry) -> [LibraryEntry] {
        let ids = model.content?.texts(using: entry.id) ?? []
        let entries = model.entries
        return ids.compactMap { id in entries.first { $0.id == id } }.prefix(8).map { $0 }
    }
}
