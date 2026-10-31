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
                Section("Meanings") {
                    ForEach(Array(entry.senses.filter { !$0.retired }.enumerated()), id: \.element.id) { n, sense in
                        senseRow(n + 1, sense, entry: entry)
                    }
                }
                let texts = inYourTexts(entry)
                if !texts.isEmpty {
                    Section("In your texts") {
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
            .navigationTitle(entry.headword)
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
        } else {
            EmptyState(title: "Not in this dictionary", message: LemmaID.headword(of: lemmaID), systemImage: "questionmark.circle")
        }
    }

    private func header(_ entry: Entry) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(italian: entry.headwordWithArticle)
                    .font(.system(size: 30, weight: .bold, design: .serif))
                Button {
                    model.speech.say(entry.headword)
                } label: {
                    Image(systemName: "speaker.wave.2.fill").frame(width: 44, height: 44)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("Play \(entry.headword)")
            }
            HStack(spacing: 8) {
                Text(PartOfSpeech.label(entry.pos))
                if let ipa = entry.ipa, !ipa.isEmpty { Text("/\(ipa)/") }
                if let gender = entry.genderLabel { Text(gender) }
                if let plural = entry.plural, !plural.isEmpty { Text("plural \(plural)").italian() }
            }
            .font(.subheadline)
            .foregroundStyle(.secondary)
            if entry.pos == "v" {
                NavigationLink(value: Route.verb(lemmaID: entry.id, formTag: nil)) {
                    Label("Conjugation", systemImage: "tablecells")
                }
                .padding(.top, 4)
            }
        }
        .padding(.vertical, 4)
    }

    private func senseRow(_ number: Int, _ sense: Sense, entry: Entry) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("\(number).").monospacedDigit().foregroundStyle(.secondary)
                Text(sense.gloss)
            }
            ForEach(sense.examples.prefix(2), id: \.italian) { ex in
                VStack(alignment: .leading, spacing: 1) {
                    Text(italian: ex.italian).font(.system(.subheadline, design: .serif)).italic()
                    if let en = ex.english { Text(en).font(.footnote).foregroundStyle(.secondary) }
                }
                .padding(.leading, 22)
            }
            let item = wordItem(sense, entry: entry)
            RememberRow(item: item, title: entry.headword, detail: sense.gloss)
                .padding(.leading, 22)
        }
        .padding(.vertical, 4)
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
