import Foundation
import ItalianCore
import LexiconKit

/// One verb form in a table.
public struct ConjugatedForm: Sendable, Hashable, Identifiable {
    public let tag: FormTag
    public let text: String          // "vado", "sono andato/a"
    public let isIrregular: Bool
    public var id: String { tag.description }
}

public struct TenseBlock: Sendable, Hashable, Identifiable {
    public let mood: Mood
    public let tense: Tense
    public let forms: [ConjugatedForm]
    public var id: String { "\(mood.rawValue).\(tense.rawValue)" }
    public var title: String { tense.italianName(in: mood) }
}

public struct ConjugationTable: Sendable, Hashable {
    public let lemmaID: String
    public let infinitive: String
    public let auxiliary: String?          // essere | avere | both
    public let participle: String?
    public let gerund: String?
    public let blocks: [TenseBlock]

    public var isIrregular: Bool { blocks.contains { $0.forms.contains(where: \.isIrregular) } }

    public func blocks(for mood: Mood) -> [TenseBlock] { blocks.filter { $0.mood == mood } }

    public func form(for tag: FormTag) -> ConjugatedForm? {
        blocks.first { $0.mood == tag.mood && $0.tense == tag.tense }?.forms.first { $0.tag.person == tag.person }
    }

    /// "sarei, saresti, sarebbe, saremmo, sareste, sarebbero" for a card's back.
    public func row(for tag: FormTag) -> String? {
        guard let block = blocks.first(where: { $0.mood == tag.mood && $0.tense == tag.tense }) else { return nil }
        return block.forms.map(\.text).joined(separator: ", ")
    }
}

/// Builds verb tables: simple tenses from the content DB, compound tenses from auxiliary plus past
/// participle, with agreement shown for essere verbs (andato/a/i/e) (HANDOFF.md 3.3).
public struct Conjugator: Sendable {
    public let content: ContentDatabase

    public init(content: ContentDatabase) {
        self.content = content
    }

    static let simpleOrder: [(Mood, Tense)] = [
        (.ind, .pres), (.ind, .impf), (.ind, .prem), (.ind, .fut),
        (.sub, .pres), (.sub, .impf), (.cond, .pres), (.imp, .pres),
    ]
    /// Compound tense -> the auxiliary's simple tense it is built on.
    static let compound: [(Mood, Tense, Mood, Tense)] = [
        (.ind, .pp, .ind, .pres), (.ind, .tpp, .ind, .impf), (.ind, .tpr, .ind, .prem), (.ind, .futa, .ind, .fut),
        (.sub, .pass, .sub, .pres), (.sub, .tpp, .sub, .impf), (.cond, .pass, .cond, .pres),
    ]

    public func table(for lemmaID: String) -> ConjugationTable? {
        guard let entry = content.entry(lemmaID), entry.pos == "v" else { return nil }
        var byTag: [String: String] = [:]
        for f in content.forms(of: entry.id) where !f.tag.isEmpty {
            // keep the first spelling per tag (kaikki lists the standard one first)
            if byTag[f.tag] == nil { byTag[f.tag] = f.form }
        }
        func regular(_ tag: FormTag, _ form: String) -> Bool {
            RegularConjugator.forms(infinitive: entry.headword, tag: tag).contains(form.lowercased())
        }
        var blocks: [TenseBlock] = []
        for (mood, tense) in Self.simpleOrder {
            let persons: [Person] = mood == .imp ? [.s2, .s3, .p1, .p2, .p3] : Person.allCases
            let forms: [ConjugatedForm] = persons.compactMap { person in
                let tag = FormTag(mood: mood, tense: tense, person: person)
                guard let text = byTag[tag.description] else { return nil }
                return ConjugatedForm(tag: tag, text: text, isIrregular: !regular(tag, text))
            }
            if !forms.isEmpty { blocks.append(TenseBlock(mood: mood, tense: tense, forms: forms)) }
        }
        let participle = byTag["part.pass"]
        let auxName = entry.auxiliary ?? "avere"
        if let participle {
            let aux: Auxiliary = auxName == "essere" ? .essere : .avere
            let auxTable = auxiliaryForms(aux)
            for (mood, tense, auxMood, auxTense) in Self.compound {
                let forms: [ConjugatedForm] = Person.allCases.compactMap { person in
                    let auxTag = FormTag(mood: auxMood, tense: auxTense, person: person)
                    guard let auxForm = auxTable[auxTag.description] else { return nil }
                    let tag = FormTag(mood: mood, tense: tense, person: person,
                                      auxiliary: auxName == "both" ? aux : nil)
                    let part = aux == .essere ? Self.agreement(participle, plural: person.isPlural) : participle
                    return ConjugatedForm(tag: tag, text: "\(auxForm) \(part)", isIrregular: false)
                }
                if !forms.isEmpty { blocks.append(TenseBlock(mood: mood, tense: tense, forms: forms)) }
            }
        }
        if let neg = byTag["imp.neg.2s"] {
            let tag = FormTag(mood: .imp, tense: .neg, person: .s2)
            blocks.append(TenseBlock(mood: .imp, tense: .neg, forms: [ConjugatedForm(tag: tag, text: "non \(neg)", isIrregular: false)]))
        }
        return ConjugationTable(lemmaID: entry.id, infinitive: entry.headword, auxiliary: entry.auxiliary,
                                participle: participle, gerund: byTag["ger.pres"], blocks: blocks)
    }

    func auxiliaryForms(_ aux: Auxiliary) -> [String: String] {
        guard let lemma = content.lemmas(headword: aux.infinitive).first(where: { $0.pos == "v" }) else { return [:] }
        var result: [String: String] = [:]
        for f in content.forms(of: lemma.id) where !f.tag.isEmpty && result[f.tag] == nil {
            result[f.tag] = f.form
        }
        return result
    }

    /// andato -> andato/a, andati/e.
    static func agreement(_ participle: String, plural: Bool) -> String {
        guard participle.hasSuffix("o") else { return participle }
        let stem = participle.dropLast()
        return plural ? "\(stem)i/e" : "\(stem)o/a"
    }

    /// The text of one form, compound tenses included, e.g. for a Verb form card.
    public func text(lemmaID: String, tag: FormTag) -> String? {
        table(for: lemmaID)?.form(for: tag)?.text
    }
}
