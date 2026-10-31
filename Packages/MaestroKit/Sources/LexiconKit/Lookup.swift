import Foundation
import ItalianCore

/// The lookup cascade of HANDOFF.md 3.2, stopping at the first step that finds something:
/// normalise and split elisions; exact headword and inflected form (every reading of an ambiguous
/// form); clitic split; an optional lemmatizer (NLTagger in the app); accent-insensitive and prefix
/// suggestions; several words offer sentence translation.
public struct Lookup: Sendable {
    public let content: ContentDatabase
    /// Last-resort lemmatizer, e.g. NaturalLanguage's NLTagger, which isn't available on Linux.
    public let lemmatizer: (@Sendable (String) -> String?)?

    public init(content: ContentDatabase, lemmatizer: (@Sendable (String) -> String?)? = nil) {
        self.content = content
        self.lemmatizer = lemmatizer
    }

    public func lookup(_ input: String) -> LookupOutcome {
        let query = Normalizer.query(input)
        guard !query.isEmpty else { return .empty }

        if query.contains(" ") {
            let phrase = readings(for: query)
            if !phrase.isEmpty { return .readings(phrase) }
            return .phrase(query)
        }

        let pieces = Normalizer.splitElision(query)
        if pieces.count > 1 {
            let all = pieces.flatMap { readings(for: $0) }
            if !all.isEmpty { return .readings(all) }
        }

        let direct = readings(for: query)
        if !direct.isEmpty { return .readings(direct) }

        let clitic = cliticReadings(for: query)
        if !clitic.isEmpty { return .readings(clitic) }

        if let lemmatizer, let lemma = lemmatizer(query), lemma != query {
            let tagged = content.lemmas(headword: lemma).map {
                Reading(lemma: $0, formTag: nil, genderNumber: nil, surface: query, via: .tagger)
            }
            if !tagged.isEmpty { return .readings(tagged) }
        }

        var suggestions = content.foldedMatches(Normalizer.fold(query))
        if suggestions.isEmpty { suggestions = content.prefixMatches(query) }
        return suggestions.isEmpty ? .empty : .suggestions(suggestions)
    }

    /// Headword and form matches, most useful first: lemmas whose headword is the query, then verbs.
    public func readings(for form: String) -> [Reading] {
        var result: [Reading] = []
        var seen = Set<String>()
        func add(_ r: Reading) {
            if seen.insert(r.id).inserted { result.append(r) }
        }
        for analysis in content.analyses(of: form) + (form == form.lowercased() ? [] : content.analyses(of: form.lowercased())) {
            add(reading(lemma: analysis.lemma, tag: analysis.tag, surface: form, via: .form))
        }
        for lemma in content.lemmas(headword: form) {
            if !result.contains(where: { $0.lemma.id == lemma.id }) {
                add(Reading(lemma: lemma, formTag: nil, genderNumber: nil, surface: form, via: .headword))
            }
        }
        return result.sorted { a, b in
            let aBase = a.formTag == nil && a.genderNumber == nil ? 0 : 1
            let bBase = b.formTag == nil && b.genderNumber == nil ? 0 : 1
            if aBase != bBase { return aBase < bBase }
            if (a.lemma.pos == "v") != (b.lemma.pos == "v") { return a.lemma.pos == "v" }
            return a.lemma.id.count < b.lemma.id.count
        }
    }

    func reading(lemma: LemmaSummary, tag: String, surface: String, via: Reading.Via) -> Reading {
        // The infinitive of a verb is its headword: present it as the base form.
        if let formTag = FormTag(tag), !(formTag.mood == .inf && formTag.tense == .pres && surface == lemma.headword) {
            return Reading(lemma: lemma, formTag: formTag, genderNumber: nil, surface: surface, via: via)
        }
        return Reading(lemma: lemma, formTag: nil, genderNumber: GenderNumber(rawValue: tag), surface: surface, via: via)
    }

    func cliticReadings(for word: String) -> [Reading] {
        for candidate in CliticSplitter.candidates(for: word) {
            let verbs = content.analyses(of: candidate.base).filter { $0.lemma.pos == "v" }
            if !verbs.isEmpty {
                return verbs.map {
                    reading(lemma: $0.lemma, tag: $0.tag, surface: word,
                            via: .clitics(base: candidate.base, clitics: candidate.clitics))
                }
            }
        }
        return []
    }
}
