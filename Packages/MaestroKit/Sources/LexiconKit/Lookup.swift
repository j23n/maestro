import Foundation
import LanguageCore

/// The lookup cascade of HANDOFF.md 3.2, stopping at the first step that finds something:
/// normalise and split elisions; exact headword and inflected form (every reading of an ambiguous
/// form); clitic split; an optional lemmatizer (NLTagger in the app); accent-insensitive and prefix
/// suggestions; several words offer sentence translation.
///
/// German skips the elision and clitic steps. It finds nouns whatever their case as typed (haus finds
/// Haus), reads umlauts typed as ae, oe and ue, and reads an unknown compound through its last part
/// (Haustür through Tür). `readings(verb:particle:)` joins a separable verb's particle back on.
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

        let german = content.language == .de
        if query.contains(" ") {
            let phrase = readings(for: query)
            if !phrase.isEmpty { return .readings(phrase) }
            // A separable verb typed as a main clause writes it: rufe an.
            let words = query.split(separator: " ").map(String.init)
            if german, words.count == 2 {
                let separable = readings(verb: words[0], particle: words[1])
                if !separable.isEmpty { return .readings(separable) }
            }
            return .phrase(query)
        }

        if !german {
            let pieces = Normalizer.splitElision(query)
            if pieces.count > 1 {
                let all = pieces.flatMap { readings(for: $0) }
                if !all.isEmpty { return .readings(all) }
            }
        }

        let direct = readings(for: query)
        if !direct.isEmpty { return .readings(direct) }

        if german {
            let umlauts = Normalizer.umlauts(query)
            if umlauts != query {
                let spelled = readings(for: umlauts)
                if !spelled.isEmpty { return .readings(spelled) }
            }
            for spelling in umlauts != query ? [query, umlauts] : [query] {
                let compound = compoundReadings(for: spelling)
                if !compound.isEmpty { return .readings(compound) }
            }
        } else {
            let clitic = cliticReadings(for: query)
            if !clitic.isEmpty { return .readings(clitic) }
        }

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
        for spelling in spellings(of: form) {
            for analysis in content.analyses(of: spelling) {
                add(reading(lemma: analysis.lemma, tag: analysis.tag, surface: form, via: .form))
            }
        }
        for spelling in spellings(of: form) {
            for lemma in content.lemmas(headword: spelling) where !result.contains(where: { $0.lemma.id == lemma.id }) {
                add(Reading(lemma: lemma, formTag: nil, genderNumber: nil, surface: form, via: .headword))
            }
        }
        if content.language == .de { result = Self.collapsingCases(result) }
        return result.sorted { a, b in
            let aBase = a.formTag == nil && a.genderNumber == nil && a.caseTag == nil ? 0 : 1
            let bBase = b.formTag == nil && b.genderNumber == nil && b.caseTag == nil ? 0 : 1
            if aBase != bBase { return aBase < bBase }
            if (a.lemma.pos == "v") != (b.lemma.pos == "v") { return a.lemma.pos == "v" }
            return a.lemma.id.count < b.lemma.id.count
        }
    }

    /// A German noun spells several cases alike (Haus is nominative, accusative and dative). Where one of
    /// them is the nominative, the dictionary shows the form once, as the nominative, and not at all when
    /// it is the headword's own nominative singular, which the plain headword reading already shows. Forms
    /// that aren't a nominative keep every case (Menschen: Akkusativ, Dativ and Genitiv Singular).
    static func collapsingCases(_ readings: [Reading]) -> [Reading] {
        func plain(_ r: Reading) -> CaseTag? {
            guard let tag = r.caseTag, tag.degree == nil, tag.declension == nil, tag.grammaticalCase != nil else { return nil }
            return tag
        }
        func group(_ r: Reading) -> String { "\(r.lemma.id)|\(r.surface)|\(plain(r)?.number?.rawValue ?? "")" }
        let hasBase = Set(readings.filter { $0.formTag == nil && $0.genderNumber == nil && $0.caseTag == nil }
            .map { "\($0.lemma.id)|\($0.surface)" })
        var nominative: [String: Reading] = [:]
        for r in readings where plain(r)?.grammaticalCase == .nom && nominative[group(r)] == nil {
            nominative[group(r)] = r
        }
        return readings.filter { r in
            guard let tag = plain(r) else { return true }
            if let nom = nominative[group(r)], nom.id != r.id { return false }
            let isOwnNominative = tag.grammaticalCase == .nom && tag.number != .pl
            return !(isOwnNominative && hasBase.contains("\(r.lemma.id)|\(r.surface)"))
        }
    }

    /// The spellings to try for a form: as given and lowercased; German also capitalized, since its nouns
    /// are spelled with a capital and queries are lowercased (haus finds Haus).
    func spellings(of form: String) -> [String] {
        var out = [form]
        let lower = form.lowercased()
        if lower != form { out.append(lower) }
        if content.language == .de {
            let capitalized = lower.prefix(1).uppercased() + lower.dropFirst()
            if !out.contains(capitalized) { out.append(capitalized) }
        }
        return out
    }

    func reading(lemma: LemmaSummary, tag: String, surface: String, via: Reading.Via) -> Reading {
        // The infinitive of a verb is its headword: present it as the base form.
        let isHeadword = surface.compare(lemma.headword, options: .caseInsensitive) == .orderedSame
        if let formTag = FormTag(tag), !(formTag.mood == .inf && formTag.tense == .pres && isHeadword) {
            return Reading(lemma: lemma, formTag: formTag, genderNumber: nil, surface: surface, via: via)
        }
        if content.language == .de {
            return Reading(lemma: lemma, formTag: nil, genderNumber: nil, surface: surface, via: via, caseTag: CaseTag(tag))
        }
        return Reading(lemma: lemma, formTag: nil, genderNumber: GenderNumber(rawValue: tag), surface: surface, via: via)
    }

    /// A German separable verb whose particle stands apart in the sentence: "rufe" with "an" reads as
    /// anrufen. The dictionary keeps the joined form (anrufe), so the particle goes back on the front.
    public func readings(verb: String, particle: String) -> [Reading] {
        let joined = Normalizer.query(particle) + Normalizer.query(verb)
        return content.analyses(of: joined).filter { $0.lemma.pos == "v" }.map {
            reading(lemma: $0.lemma, tag: $0.tag, surface: verb, via: .separable(particle: Normalizer.query(particle)))
        }
    }

    /// German compounds the dictionary lacks, read through their last part: Haustür is a Tür. The head
    /// is the longest final part that is a noun, and the rest must be a word too, with or without a
    /// linking s, es, n or en (Arbeitsplatz, Sonnenschein).
    func compoundReadings(for word: String) -> [Reading] {
        let w = word.lowercased()
        let letters = Array(w)
        guard letters.count >= 6 else { return [] }
        for split in 3...(letters.count - 3) {
            let head = String(letters[split...])
            let modifier = String(letters[..<split])
            let nouns = readings(for: head).filter { $0.lemma.pos == "n" }
            guard !nouns.isEmpty, knowsModifier(modifier) else { continue }
            let first = modifier.prefix(1).uppercased() + modifier.dropFirst()
            let last = head.prefix(1).uppercased() + head.dropFirst()
            return nouns.map {
                Reading(lemma: $0.lemma, formTag: nil, genderNumber: nil, surface: word,
                        via: .compound(parts: [first, last]), caseTag: $0.caseTag)
            }
        }
        return []
    }

    func knowsModifier(_ modifier: String) -> Bool {
        var stems = [modifier]
        for link in ["es", "en", "s", "n"] where modifier.hasSuffix(link) && modifier.count > link.count + 2 {
            stems.append(String(modifier.dropLast(link.count)))
        }
        // A verb stem as modifier: Wohnzimmer = wohn(en) + Zimmer.
        stems += stems.map { $0 + "en" }
        return stems.contains { stem in spellings(of: stem).contains { !content.analyses(of: $0).isEmpty || !content.lemmas(headword: $0).isEmpty } }
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
