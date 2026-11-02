/// Verb form tags, HANDOFF.md 6.5: `mood.tense[.person][+aux]`, e.g. `cond.pass.1p`, `ind.pp.3s+e`.
/// German uses the same syntax with its own codes (`ind.prat.1s`, `k2.wuerde.1s`, `ind.perf.3s+s`),
/// read in the language of the lemma; labels take that language (`label(in:)`).
public enum Mood: String, Sendable, CaseIterable, Codable, Hashable {
    case ind, sub, cond, imp, inf, ger, part
    /// German: Konjunktiv I and II.
    case k1, k2

    /// The moods a language uses, in table order.
    public static func moods(in language: Language) -> [Mood] {
        switch language {
        case .it: [.ind, .sub, .cond, .imp, .inf, .ger, .part]
        case .de: [.ind, .k1, .k2, .imp, .inf, .part]
        }
    }

    public var italianName: String {
        switch self {
        case .ind: "indicativo"
        case .sub: "congiuntivo"
        case .cond: "condizionale"
        case .imp: "imperativo"
        case .inf: "infinito"
        case .ger: "gerundio"
        case .part: "participio"
        case .k1, .k2: germanName
        }
    }

    public var germanName: String {
        switch self {
        case .ind: "Indikativ"
        case .k1: "Konjunktiv I"
        case .k2: "Konjunktiv II"
        case .imp: "Imperativ"
        case .inf: "Infinitiv"
        case .part: "Partizip"
        case .sub: "Konjunktiv"
        case .cond: "Konditional"
        case .ger: "Gerundium"
        }
    }

    public func name(in language: Language) -> String {
        language == .de ? germanName : italianName
    }

    public var isFinite: Bool {
        switch self {
        case .ind, .sub, .cond, .imp, .k1, .k2: true
        case .inf, .ger, .part: false
        }
    }
}

public enum Tense: String, Sendable, CaseIterable, Codable, Hashable {
    case pres, impf, prem, fut, pp, tpp, tpr, futa, pass, neg
    /// German: Präteritum, Perfekt, Plusquamperfekt, Futur I and II, würde + infinitive, zu-infinitive.
    case prat, perf, pqp, fut1, fut2, wuerde, zu

    /// Tenses the app builds from an auxiliary (or werden, würde) rather than reading from the dictionary.
    public var isCompound: Bool {
        switch self {
        case .pp, .tpp, .tpr, .futa, .pass, .perf, .pqp, .fut1, .fut2, .wuerde: true
        case .pres, .impf, .prem, .fut, .neg, .prat, .zu: false
        }
    }

    /// The Italian name of the tense within a mood ("trapassato" alone in the congiuntivo).
    public func italianName(in mood: Mood) -> String {
        switch self {
        case .pres: "presente"
        case .impf: "imperfetto"
        case .prem: "passato remoto"
        case .fut: "futuro semplice"
        case .pp: "passato prossimo"
        case .tpp: mood == .sub ? "trapassato" : "trapassato prossimo"
        case .tpr: "trapassato remoto"
        case .futa: "futuro anteriore"
        case .pass: "passato"
        case .neg: "negativo"
        case .prat, .perf, .pqp, .fut1, .fut2, .wuerde, .zu: germanName(in: mood)
        }
    }

    /// The German name of the tense within a mood ("Präteritum", "würde-Form").
    public func germanName(in mood: Mood) -> String {
        switch self {
        case .pres: "Präsens"
        case .prat: "Präteritum"
        case .perf: "Perfekt"
        case .pqp: "Plusquamperfekt"
        case .fut1: "Futur I"
        case .fut2: "Futur II"
        case .wuerde: "würde-Form"
        case .zu: "mit zu"
        case .pass: mood == .part ? "Perfekt" : "Vergangenheit"
        case .impf: "Imperfekt"
        case .prem: "Präteritum"
        case .fut: "Futur"
        case .pp: "Perfekt"
        case .tpp, .tpr: "Plusquamperfekt"
        case .futa: "Futur II"
        case .neg: "verneint"
        }
    }

    public func name(in mood: Mood, language: Language) -> String {
        language == .de ? germanName(in: mood) : italianName(in: mood)
    }
}

public enum Person: String, Sendable, CaseIterable, Codable, Hashable {
    case s1 = "1s", s2 = "2s", s3 = "3s", p1 = "1p", p2 = "2p", p3 = "3p"

    public var pronoun: String {
        switch self {
        case .s1: "io"
        case .s2: "tu"
        case .s3: "lui/lei"
        case .p1: "noi"
        case .p2: "voi"
        case .p3: "loro"
        }
    }

    public var germanPronoun: String {
        switch self {
        case .s1: "ich"
        case .s2: "du"
        case .s3: "er/sie/es"
        case .p1: "wir"
        case .p2: "ihr"
        case .p3: "sie/Sie"
        }
    }

    public func pronoun(in language: Language) -> String {
        language == .de ? germanPronoun : pronoun
    }

    public var isPlural: Bool { self == .p1 || self == .p2 || self == .p3 }
}

public enum Auxiliary: String, Sendable, Codable, Hashable {
    case essere = "e", avere = "a"
    /// German: haben and sein.
    case haben = "h", sein = "s"

    public var infinitive: String {
        switch self {
        case .essere: "essere"
        case .avere: "avere"
        case .haben: "haben"
        case .sein: "sein"
        }
    }
}

public struct FormTag: Hashable, Sendable, CustomStringConvertible {
    public var mood: Mood
    public var tense: Tense
    public var person: Person?
    public var auxiliary: Auxiliary?

    public init(mood: Mood, tense: Tense, person: Person? = nil, auxiliary: Auxiliary? = nil) {
        self.mood = mood
        self.tense = tense
        self.person = person
        self.auxiliary = auxiliary
    }

    public init?(_ string: String) {
        let pieces = string.split(separator: "+", maxSplits: 1, omittingEmptySubsequences: false)
        let core = pieces[0].split(separator: ".").map(String.init)
        guard core.count == 2 || core.count == 3,
              let mood = Mood(rawValue: core[0]),
              let tense = Tense(rawValue: core[1]) else { return nil }
        var person: Person?
        if core.count == 3 {
            guard let p = Person(rawValue: core[2]) else { return nil }
            person = p
        }
        guard mood.isFinite == (person != nil) else { return nil }
        var aux: Auxiliary?
        if pieces.count == 2 {
            guard let a = Auxiliary(rawValue: String(pieces[1])) else { return nil }
            aux = a
        }
        self.init(mood: mood, tense: tense, person: person, auxiliary: aux)
    }

    public var description: String {
        var s = "\(mood.rawValue).\(tense.rawValue)"
        if let person { s += ".\(person.rawValue)" }
        if let auxiliary { s += "+\(auxiliary.rawValue)" }
        return s
    }

    /// The tag without person and auxiliary: `cond.pass`.
    public var tenseKey: String { "\(mood.rawValue).\(tense.rawValue)" }

    /// "condizionale passato" for Italian, "Konjunktiv II Präteritum" for German.
    public func tenseLabel(in language: Language) -> String {
        guard language == .de else { return tenseLabel }
        switch (mood, tense) {
        case (.ind, _): return tense.germanName(in: mood)
        case (.imp, _): return "Imperativ"
        case (.inf, .pres): return "Infinitiv"
        case (.inf, .zu): return "Infinitiv mit zu"
        case (.inf, .perf): return "Infinitiv Perfekt"
        case (.part, .pres): return "Partizip I"
        case (.part, .pass): return "Partizip II"
        case (.k2, .wuerde): return "würde-Form"
        default: return "\(mood.germanName) \(tense.germanName(in: mood))"
        }
    }

    /// Short form for tight spaces: "cond. passato", "Konj. II Präteritum".
    public func shortTenseLabel(in language: Language) -> String {
        guard language == .de else { return shortTenseLabel }
        switch mood {
        case .k1: return "Konj. I \(tense.germanName(in: mood))"
        case .k2: return tense == .wuerde ? "würde-Form" : "Konj. II \(tense.germanName(in: mood))"
        default: return tenseLabel(in: language)
        }
    }

    /// "condizionale passato · noi", "Präteritum · ich".
    public func label(in language: Language) -> String {
        if let person { return "\(tenseLabel(in: language)) · \(person.pronoun(in: language))" }
        return tenseLabel(in: language)
    }

    /// "condizionale passato", "indicativo imperfetto", "imperativo", "participio passato".
    public var tenseLabel: String {
        switch (mood, tense) {
        case (.imp, .pres): "imperativo"
        case (.imp, .neg): "imperativo negativo"
        case (.inf, .pres): "infinito"
        case (.ger, .pres): "gerundio"
        case (.part, .pres): "participio presente"
        case (.part, .pass): "participio passato"
        case (.inf, .pass): "infinito passato"
        case (.ger, .pass): "gerundio passato"
        default: "\(mood.italianName) \(tense.italianName(in: mood))"
        }
    }

    /// Short form for tight spaces: "cond. passato".
    public var shortTenseLabel: String {
        let moodShort: String
        switch mood {
        case .ind: moodShort = "ind."
        case .sub: moodShort = "cong."
        case .cond: moodShort = "cond."
        case .imp: return tenseLabel
        case .inf, .ger, .part: return tenseLabel
        case .k1, .k2: return shortTenseLabel(in: .de)
        }
        return "\(moodShort) \(tense.italianName(in: mood))"
    }

    /// "condizionale passato · noi"
    public var label: String {
        if let person { return "\(tenseLabel) · \(person.pronoun)" }
        return tenseLabel
    }
}

extension FormTag: Codable {
    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let raw = try container.decode(String.self)
        guard let tag = FormTag(raw) else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "invalid form tag \(raw)")
        }
        self = tag
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(description)
    }
}

/// Gender and number of nouns, adjectives and participle agreement: ms fs mp fp.
public enum GenderNumber: String, Sendable, Codable, Hashable, CaseIterable {
    case ms, fs, mp, fp

    public var label: String {
        switch self {
        case .ms: "masculine singular"
        case .fs: "feminine singular"
        case .mp: "masculine plural"
        case .fp: "feminine plural"
        }
    }
}

/// A German noun, adjective, article or pronoun form in the content DB (HANDOFF.md 6.5):
/// `[comp.|sup.][decl.]case[.gn]`, such as `gen.ns` (Hauses), `str.nom.ms` (guter), `comp` (besser).
public struct CaseTag: Hashable, Sendable, CustomStringConvertible {
    public enum Case: String, Sendable, CaseIterable, Hashable {
        case nom, acc, dat, gen

        public var germanName: String {
            switch self {
            case .nom: "Nominativ"
            case .acc: "Akkusativ"
            case .dat: "Dativ"
            case .gen: "Genitiv"
            }
        }
    }

    /// Gender and number: German plurals have no gender.
    public enum Number: String, Sendable, CaseIterable, Hashable {
        case ms, fs, ns, pl

        public var germanName: String {
            switch self {
            case .ms: "maskulin Singular"
            case .fs: "feminin Singular"
            case .ns: "neutral Singular"
            case .pl: "Plural"
            }
        }
    }

    public enum Declension: String, Sendable, CaseIterable, Hashable {
        case str, wk, mix

        public var germanName: String {
            switch self {
            case .str: "stark"
            case .wk: "schwach"
            case .mix: "gemischt"
            }
        }
    }

    public enum Degree: String, Sendable, CaseIterable, Hashable {
        case comp, sup

        public var germanName: String { self == .comp ? "Komparativ" : "Superlativ" }
    }

    public var degree: Degree?
    public var declension: Declension?
    public var grammaticalCase: Case?
    public var number: Number?

    public init(degree: Degree? = nil, declension: Declension? = nil, grammaticalCase: Case?, number: Number? = nil) {
        self.degree = degree
        self.declension = declension
        self.grammaticalCase = grammaticalCase
        self.number = number
    }

    public init?(_ string: String) {
        var parts = string.split(separator: ".").map(String.init)
        guard !parts.isEmpty else { return nil }
        var degree: Degree?
        if let d = Degree(rawValue: parts[0]) {
            degree = d
            parts.removeFirst()
            if parts.isEmpty {
                self.init(degree: d, grammaticalCase: nil)
                return
            }
        }
        var declension: Declension?
        if let d = Declension(rawValue: parts[0]) {
            declension = d
            parts.removeFirst()
        }
        guard let first = parts.first, let c = Case(rawValue: first), parts.count <= 2 else { return nil }
        var number: Number?
        if parts.count == 2 {
            guard let n = Number(rawValue: parts[1]) else { return nil }
            number = n
        }
        self.init(degree: degree, declension: declension, grammaticalCase: c, number: number)
    }

    public var description: String {
        [degree?.rawValue, declension?.rawValue, grammaticalCase?.rawValue, number?.rawValue]
            .compactMap { $0 }.joined(separator: ".")
    }

    /// "Genitiv neutral Singular", "Komparativ, stark, Nominativ maskulin Singular", "Komparativ".
    public var label: String {
        var parts: [String] = []
        if let degree { parts.append(degree.germanName) }
        if let declension { parts.append(declension.germanName) }
        if let grammaticalCase {
            parts.append([grammaticalCase.germanName, number?.germanName].compactMap { $0 }.joined(separator: " "))
        }
        return parts.joined(separator: ", ")
    }
}
