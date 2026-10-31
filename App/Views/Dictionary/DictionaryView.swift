import SwiftData
import SwiftUI
import Translation
import ItalianCore
import LexiconKit

/// Dictionary search (HANDOFF.md 3.2): Italian through the lookup cascade, English over glosses,
/// several words offer translation.
struct DictionaryView: View {
    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @Environment(\.modelContext) private var context
    @Query(sort: \LookupEntry.lookedUpAt, order: .reverse) private var history: [LookupEntry]
    @State private var query = ""
    @State private var englishToItalian = false
    @State private var showTranslation = false

    var body: some View {
        List {
            if !model.hasDictionary {
                EmptyState(title: "No dictionary in this build",
                           message: "Run make content to build the dictionary database.",
                           systemImage: "character.book.closed")
            } else if query.trimmingCharacters(in: .whitespaces).isEmpty {
                recent
            } else if englishToItalian {
                englishResults
            } else {
                results
            }
        }
        .navigationTitle("Dictionary")
        .searchable(text: $query, prompt: englishToItalian ? "English word" : "Italian word or form")
        .autocorrectionDisabled()
        #if os(iOS)
        .textInputAutocapitalization(.never)
        #endif
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Picker("Direction", selection: $englishToItalian) {
                    Text("IT → EN").tag(false)
                    Text("EN → IT").tag(true)
                }
                .pickerStyle(.segmented)
                .accessibilityLabel("Search direction")
            }
        }
        .translationPresentation(isPresented: $showTranslation, text: query)
    }

    @ViewBuilder private var recent: some View {
        let unique = uniqueHistory
        if unique.isEmpty {
            Text("Type a word in any form: *andavamo*, *dammelo*, *perche*.")
                .foregroundStyle(.secondary)
        } else {
            Section("Recent") {
                ForEach(unique, id: \.lemmaID) { entry in
                    if let lemma = model.content?.lemma(entry.lemmaID) {
                        NavigationLink(value: Route.entry(lemma.id)) {
                            LemmaRow(lemma: lemma)
                        }
                    }
                }
            }
        }
    }

    private var uniqueHistory: [LookupEntry] {
        var seen = Set<String>()
        return history.filter { !$0.lemmaID.isEmpty && seen.insert($0.lemmaID).inserted }.prefix(20).map { $0 }
    }

    @ViewBuilder private var results: some View {
        switch model.lookup?.lookup(query) ?? .empty {
        case .readings(let readings):
            Section(readings.count > 1 ? "\(readings.count) readings" : "Result") {
                ForEach(readings) { reading in
                    ReadingRow(reading: reading) { record(reading.lemma.id) }
                }
            }
        case .suggestions(let lemmas):
            Section("Did you mean") {
                ForEach(lemmas) { lemma in
                    NavigationLink(value: Route.entry(lemma.id)) { LemmaRow(lemma: lemma) }
                        .simultaneousGesture(TapGesture().onEnded { record(lemma.id) })
                }
            }
        case .phrase(let phrase):
            Section {
                Button {
                    showTranslation = true
                } label: {
                    Label("Translate “\(phrase)”", systemImage: "translate")
                        .frame(minHeight: 44)
                }
            } footer: {
                Text("Several words: Apple's on-device translation, once its Italian model is downloaded.")
            }
        case .empty:
            Text("No match for “\(query)”.").foregroundStyle(.secondary)
        }
    }

    @ViewBuilder private var englishResults: some View {
        let lemmas = model.content?.englishMatches(query) ?? []
        if lemmas.isEmpty {
            Text("No Italian word found for “\(query)”.").foregroundStyle(.secondary)
        } else {
            Section {
                ForEach(lemmas) { lemma in
                    NavigationLink(value: Route.entry(lemma.id)) { LemmaRow(lemma: lemma) }
                }
            } footer: {
                Text("English search looks through the dictionary's English glosses.")
            }
        }
    }

    private func record(_ lemmaID: String) {
        RememberStore(context: context, prefs: prefs, content: model.content)
            .recordLookup(query: Normalizer.query(query), lemmaID: lemmaID)
    }
}

struct LemmaRow: View {
    let lemma: LemmaSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text(italian: lemma.headword).font(.system(.body, design: .serif).weight(.semibold))
                Text(lemma.posLabel).font(.caption).foregroundStyle(.secondary)
            }
            if !lemma.firstGloss.isEmpty {
                Text(lemma.firstGloss).font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
            }
        }
        .padding(.vertical, 2)
    }
}

/// One reading of a looked-up form: lemma, parse, open buttons and Remember (HANDOFF.md 3.2).
struct ReadingRow: View {
    let reading: Reading
    let onOpen: () -> Void
    @Environment(AppModel.self) private var model

    /// Rows of their own in the list: the reading, then one per keepable item.
    var body: some View {
        Group {
            NavigationLink(value: destination) {
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Text(italian: reading.lemma.headword).font(.system(.title3, design: .serif).weight(.semibold))
                        Text(reading.lemma.posLabel).font(.caption).foregroundStyle(.secondary)
                    }
                    Text(reading.analysis).font(.subheadline)
                    if case .clitics(let base, let clitics) = reading.via {
                        Text(italian: "\(reading.surface) = \(([base] + clitics).joined(separator: " + "))")
                            .font(.subheadline).foregroundStyle(.secondary)
                    }
                    if !reading.lemma.firstGloss.isEmpty {
                        Text(reading.lemma.firstGloss).font(.subheadline).foregroundStyle(.secondary)
                    }
                }
            }
            .simultaneousGesture(TapGesture().onEnded { onOpen() })
            ForEach(items) { item in
                let text = item.rowText(model: model)
                RememberRow(item: item, title: text.title, detail: text.detail)
            }
        }
    }

    private var destination: Route {
        reading.lemma.pos == "v" ? .verb(lemmaID: reading.lemma.id, formTag: reading.formTag?.description) : .entry(reading.lemma.id)
    }

    private var items: [RememberItem] {
        var out: [RememberItem] = []
        if let sense = model.content?.entry(reading.lemma.id)?.senses.first(where: { !$0.retired }) {
            var word = RememberItem.word(lemmaID: reading.lemma.id, senseID: sense.id, surface: reading.lemma.headword)
            if let example = sense.examples.first {
                word = word.inSentence(textID: "", sentenceID: "", text: example.italian,
                                       translation: example.english ?? "", ranges: [])
            }
            out.append(word)
        }
        if let tag = reading.formTag, reading.lemma.pos == "v", !(tag.mood == .inf && tag.tense == .pres) {
            out.append(.verbForm(lemmaID: reading.lemma.id, formTag: tag.description, surface: reading.surface))
        }
        return out
    }
}
