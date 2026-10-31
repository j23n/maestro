import SwiftData
import SwiftUI
import ItalianCore
import LexiconKit

/// Verbs and grammar home (HANDOFF.md 3.3): search accepting any form, recent verbs, common
/// irregular verbs, grammar topics.
struct VerbsHomeView: View {
    @Environment(AppModel.self) private var model
    @Query(sort: \LookupEntry.lookedUpAt, order: .reverse) private var history: [LookupEntry]
    @State private var query = ""
    @Environment(\.openRoute) private var openRoute

    static let commonIrregular = ["essere", "avere", "andare", "fare", "dire", "venire", "stare", "dare", "potere",
                                  "volere", "dovere", "sapere", "uscire", "bere", "vedere", "prendere", "mettere",
                                  "rimanere", "tenere", "scegliere"]

    var body: some View {
        List {
            if !query.isEmpty {
                searchResults
            } else {
                let recent = recentVerbs
                if !recent.isEmpty {
                    LabeledSection("Recent") {
                        ForEach(recent) { lemma in
                            NavigationLink(value: Route.verb(lemmaID: lemma.id, formTag: nil)) { LemmaRow(lemma: lemma) }
                        }
                    }
                }
                LabeledSection("Most used irregular verbs") {
                    let verbs = Self.commonIrregular.prefix(8).compactMap { hw in
                        model.content?.lemmas(headword: hw).first { $0.pos == "v" }
                    }
                    if verbs.isEmpty {
                        Text("The dictionary isn't in this build.").foregroundStyle(.secondary)
                    } else {
                        Grid(horizontalSpacing: 8, verticalSpacing: 8) {
                            ForEach(Array(stride(from: 0, to: verbs.count, by: 2)), id: \.self) { i in
                                GridRow {
                                    verbCard(verbs[i])
                                    if i + 1 < verbs.count { verbCard(verbs[i + 1]) } else { Color.clear }
                                }
                            }
                        }
                        .padding(.vertical, 4)
                        .listRowSeparator(.hidden)
                    }
                }
                LabeledSection("Grammar reference") {
                    ForEach(model.grammarTopics.prefix(8)) { topic in
                        NavigationLink(value: Route.grammar(topic.id)) { GrammarRow(topic: topic) }
                    }
                    NavigationLink(value: Route.grammarIndex) {
                        Text("All grammar topics")
                    }
                }
            }
        }
        .plainPage()
        .navigationTitle("Verbs")
        .searchable(text: $query, prompt: "Any verb form: vada, saremmo")
        #if DEBUG
        .task { if query.isEmpty, let q = UITestLaunch.query { query = q } }
        #endif
        .autocorrectionDisabled()
        #if os(iOS)
        .textInputAutocapitalization(.never)
        #endif
    }

    /// A button, not a NavigationLink: the grid is one List row, and a row with several links
    /// pushes every one of them on a tap.
    private func verbCard(_ lemma: LemmaSummary) -> some View {
        Button {
            openRoute(.verb(lemmaID: lemma.id, formTag: nil))
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(italian: lemma.headword)
                    .font(.system(.body, design: .serif).weight(.semibold))
                    .foregroundStyle(Theme.ink)
                Text(lemma.firstGloss).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12)
            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.hairline))
            .contentShape(Rectangle())
        }
        .buttonStyle(.borderless)
    }

    @ViewBuilder private var searchResults: some View {
        let readings = verbReadings
        if readings.isEmpty {
            Text("No verb found for “\(query)”.").foregroundStyle(.secondary)
        } else {
            Section {
                ForEach(readings) { reading in
                    NavigationLink(value: Route.verb(lemmaID: reading.lemma.id, formTag: reading.formTag?.description)) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(italian: reading.lemma.headword).font(.system(.body, design: .serif).weight(.semibold))
                            Text(reading.analysis).font(.subheadline).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }

    private var verbReadings: [Reading] {
        guard let lookup = model.lookup else { return [] }
        switch lookup.lookup(query) {
        case .readings(let r): return r.filter { $0.lemma.pos == "v" }
        case .suggestions(let lemmas):
            return lemmas.filter { $0.pos == "v" }.map {
                Reading(lemma: $0, formTag: nil, genderNumber: nil, surface: $0.headword, via: .headword)
            }
        default: return []
        }
    }

    private var recentVerbs: [LemmaSummary] {
        var seen = Set<String>()
        var out: [LemmaSummary] = []
        for entry in history where seen.insert(entry.lemmaID).inserted {
            if let lemma = model.content?.lemma(entry.lemmaID), lemma.pos == "v" { out.append(lemma) }
            if out.count == 6 { break }
        }
        return out
    }
}

struct GrammarRow: View {
    let topic: GrammarTopicRow
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(topic.title).font(.body.weight(.semibold))
                Text(markdown: topic.summary).font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
            }
            Spacer()
            LevelTag(level: topic.level)
        }
        .padding(.vertical, 2)
    }
}

struct GrammarIndexView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        List {
            ForEach(["A1", "A2", "B1", "B2"], id: \.self) { level in
                let topics = model.grammarTopics.filter { $0.level == level }
                if !topics.isEmpty {
                    LabeledSection(level) {
                        ForEach(topics) { topic in
                            NavigationLink(value: Route.grammar(topic.id)) { GrammarRow(topic: topic) }
                        }
                    }
                }
            }
        }
        .plainPage()
        .navigationTitle("Grammar")
    }
}
