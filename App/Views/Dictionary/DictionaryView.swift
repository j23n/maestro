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
            } else {
                directionRow
                if query.trimmingCharacters(in: .whitespaces).isEmpty {
                    recent
                } else if englishToItalian {
                    englishResults
                } else {
                    results
                }
            }
        }
        .plainPage()
        .navigationTitle("Dictionary")
        .searchable(text: $query, prompt: englishToItalian ? "English word" : "Italian word or form")
        #if DEBUG
        .task { if query.isEmpty, let q = UITestLaunch.query { query = q } }
        #endif
        .autocorrectionDisabled()
        #if os(iOS)
        .textInputAutocapitalization(.never)
        #endif
        .translationPresentation(isPresented: $showTranslation, text: query)
    }

    /// The search direction, as a small toggle under the search field (the mock's "Italian → English").
    private var directionRow: some View {
        HStack {
            Spacer()
            Button {
                englishToItalian.toggle()
            } label: {
                HStack(spacing: 4) {
                    Text(englishToItalian ? "English → Italian" : "Italian → English")
                    Image(systemName: "arrow.left.arrow.right").font(.caption2.weight(.semibold))
                }
                .font(.footnote)
                .foregroundStyle(.secondary)
                .frame(minHeight: 44)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(englishToItalian ? "Searching English to Italian. Switch to Italian to English"
                                                 : "Searching Italian to English. Switch to English to Italian")
        }
        .listRowSeparator(.hidden)
        .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 0, trailing: 16))
    }

    @ViewBuilder private var recent: some View {
        let unique = uniqueHistory
        if unique.isEmpty {
            Text("Type a word in any form: *andavamo*, *dammelo*, *perche*.")
                .foregroundStyle(.secondary)
        } else {
            LabeledSection("Recent") {
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
            LabeledSection(readings.count > 1 ? "\(readings.count) readings" : "Result") {
                ForEach(readings) { reading in
                    ReadingRow(reading: reading) { record(reading.lemma.id) }
                }
            }
        case .suggestions(let lemmas):
            LabeledSection("Did you mean") {
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

/// One reading of a looked-up form (HANDOFF.md 3.2, the Lookup mock): headword and part of
/// speech, the form's analysis when it adds something, the gloss, and one Remember button for
/// the reading's keepable item.
struct ReadingRow: View {
    let reading: Reading
    let onOpen: () -> Void
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            NavigationLink(value: destination) {
                VStack(alignment: .leading, spacing: 3) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(italian: reading.lemma.headword).font(.system(.title3, design: .serif).weight(.semibold))
                        Tag(text: reading.lemma.posLabel, colors: Theme.kind(.word))
                    }
                    if let form = formLine {
                        Text(form).font(.subheadline)
                    }
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
            if let item {
                RememberButton(item: item, title: item.rowText(model: model).title)
            }
        }
    }

    /// What this form is, without repeating the headword and part of speech shown above it:
    /// "indicativo presente · tu" or "feminine plural". Nil for the headword itself.
    private var formLine: String? {
        if let tag = reading.formTag { return tag.label }
        if let gn = reading.genderNumber { return gn.label }
        return nil
    }

    private var destination: Route {
        reading.lemma.pos == "v" ? .verb(lemmaID: reading.lemma.id, formTag: reading.formTag?.description) : .entry(reading.lemma.id)
    }

    /// The verb form for a conjugated verb, otherwise the word in its first sense.
    private var item: RememberItem? {
        if let tag = reading.formTag, reading.lemma.pos == "v", !(tag.mood == .inf && tag.tense == .pres) {
            return .verbForm(lemmaID: reading.lemma.id, formTag: tag.description, surface: reading.surface)
        }
        guard let sense = model.content?.entry(reading.lemma.id)?.senses.first(where: { !$0.retired }) else { return nil }
        let word = RememberItem.word(lemmaID: reading.lemma.id, senseID: sense.id, surface: reading.lemma.headword)
        guard let example = sense.examples.first else { return word }
        return word.inSentence(textID: "", sentenceID: "", text: example.italian,
                               translation: example.english ?? "", ranges: [])
    }
}
