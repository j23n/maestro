import Foundation
import LanguageCore
import LexiconKit

/// One case of a German noun: "des Hauses", "der Häuser".
public struct DeclensionRow: Sendable, Hashable, Identifiable {
    public let grammaticalCase: CaseTag.Case
    public let singular: String?
    public let plural: String?
    public var id: String { grammaticalCase.rawValue }
}

public struct NounDeclension: Sendable, Hashable {
    public let lemmaID: String
    public let headword: String
    public let gender: String?
    /// Nominative, accusative, dative, genitive, each with its definite article.
    public let rows: [DeclensionRow]
}

/// One declension of a German adjective: the strong, weak or mixed endings, by case and gender-number.
public struct AdjectiveBlock: Sendable, Hashable, Identifiable {
    public let declension: CaseTag.Declension
    /// Case -> gender-number -> form.
    public let forms: [CaseTag.Case: [CaseTag.Number: String]]
    public var id: String { declension.rawValue }
    public var title: String { declension.germanName }
}

public struct AdjectiveDeclension: Sendable, Hashable {
    public let lemmaID: String
    public let headword: String
    public let comparative: String?
    public let superlative: String?
    public let blocks: [AdjectiveBlock]
}

/// German noun and adjective tables from the content DB's case tags (HANDOFF.md 6.5).
public struct Decliner: Sendable {
    public let content: ContentDatabase

    public init(content: ContentDatabase) {
        self.content = content
    }

    /// The definite article for a case and gender-number: der, des, dem, den, die, das.
    public static func article(_ c: CaseTag.Case, _ number: CaseTag.Number) -> String {
        switch (c, number) {
        case (.nom, .ms): "der"
        case (.acc, .ms): "den"
        case (.dat, .ms), (.dat, .ns): "dem"
        case (.gen, .ms), (.gen, .ns): "des"
        case (.nom, .fs), (.acc, .fs), (.nom, .pl), (.acc, .pl): "die"
        case (.dat, .fs), (.gen, .fs), (.gen, .pl): "der"
        case (.nom, .ns), (.acc, .ns): "das"
        case (.dat, .pl): "den"
        }
    }

    public func noun(_ lemmaID: String) -> NounDeclension? {
        guard let entry = content.entry(lemmaID), entry.pos == "n", Language.of(id: entry.id) == .de else { return nil }
        var singular: [CaseTag.Case: String] = [:]
        var plural: [CaseTag.Case: String] = [:]
        var singularNumber: CaseTag.Number?
        for f in content.forms(of: entry.id) {
            guard let tag = CaseTag(f.tag), tag.degree == nil, tag.declension == nil,
                  let c = tag.grammaticalCase, let number = tag.number else { continue }
            if number == .pl {
                if plural[c] == nil { plural[c] = f.form }
            } else if singular[c] == nil {
                singular[c] = f.form
                singularNumber = number
            }
        }
        if singular[.nom] == nil { singular[.nom] = entry.headword }
        let number = singularNumber ?? entry.gender.flatMap { CaseTag.Number(rawValue: String($0.prefix(1)) + "s") }
        let rows = CaseTag.Case.allCases.map { c in
            DeclensionRow(grammaticalCase: c,
                          singular: singular[c].map { form in number.map { "\(Self.article(c, $0)) \(form)" } ?? form },
                          plural: plural[c].map { "\(Self.article(c, .pl)) \($0)" })
        }
        guard rows.contains(where: { $0.plural != nil }) || singular.count > 1 else { return nil }
        return NounDeclension(lemmaID: entry.id, headword: entry.headword, gender: entry.gender, rows: rows)
    }

    public func adjective(_ lemmaID: String) -> AdjectiveDeclension? {
        guard let entry = content.entry(lemmaID), entry.pos == "adj", Language.of(id: entry.id) == .de else { return nil }
        var comparative: String?
        var superlative: String?
        var tables: [CaseTag.Declension: [CaseTag.Case: [CaseTag.Number: String]]] = [:]
        for f in content.forms(of: entry.id) {
            guard let tag = CaseTag(f.tag) else { continue }
            if tag.grammaticalCase == nil {
                if tag.degree == .comp, comparative == nil { comparative = f.form }
                if tag.degree == .sup, superlative == nil { superlative = f.form }
                continue
            }
            guard tag.degree == nil, let d = tag.declension, let c = tag.grammaticalCase, let n = tag.number else { continue }
            if tables[d, default: [:]][c, default: [:]][n] == nil {
                tables[d, default: [:]][c, default: [:]][n] = f.form
            }
        }
        let blocks = CaseTag.Declension.allCases.compactMap { d in
            tables[d].map { AdjectiveBlock(declension: d, forms: $0) }
        }
        guard !blocks.isEmpty || comparative != nil else { return nil }
        return AdjectiveDeclension(lemmaID: entry.id, headword: entry.headword, comparative: comparative,
                                   superlative: superlative, blocks: blocks)
    }
}
