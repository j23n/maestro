/// Verb form tags, HANDOFF.md 6.5: `mood.tense[.person][+aux]`, e.g. `cond.pass.1p`, `ind.pp.3s+e`.
public enum Mood: String, Sendable, CaseIterable, Codable, Hashable {
    case ind, sub, cond, imp, inf, ger, part

    public var italianName: String {
        switch self {
        case .ind: "indicativo"
        case .sub: "congiuntivo"
        case .cond: "condizionale"
        case .imp: "imperativo"
        case .inf: "infinito"
        case .ger: "gerundio"
        case .part: "participio"
        }
    }

    public var isFinite: Bool {
        switch self {
        case .ind, .sub, .cond, .imp: true
        case .inf, .ger, .part: false
        }
    }
}

public enum Tense: String, Sendable, CaseIterable, Codable, Hashable {
    case pres, impf, prem, fut, pp, tpp, tpr, futa, pass, neg

    public var isCompound: Bool {
        switch self {
        case .pp, .tpp, .tpr, .futa, .pass: true
        case .pres, .impf, .prem, .fut, .neg: false
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
        }
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

    public var isPlural: Bool { self == .p1 || self == .p2 || self == .p3 }
}

public enum Auxiliary: String, Sendable, Codable, Hashable {
    case essere = "e", avere = "a"

    public var infinitive: String { self == .essere ? "essere" : "avere" }
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
