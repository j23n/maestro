import Foundation
import LanguageCore
import LexiconKit

/// German verb tables (HANDOFF.md 6.5, "German form tags"): Präsens, Präteritum, Konjunktiv I and II and
/// the imperative from the content DB; Perfekt, Plusquamperfekt, Futur I and II, the würde-Form and
/// Konjunktiv II Plusquamperfekt built from haben or sein, werden and würde.
///
/// A separable verb's finite forms are shown as a main clause writes them (rufe an); the dictionary
/// keeps them joined (anrufe), as a subordinate clause writes them.
extension Conjugator {
    static let germanSimple: [(Mood, Tense)] = [(.ind, .pres), (.ind, .prat), (.k1, .pres), (.k2, .prat), (.imp, .pres)]

    enum GermanBuild {
        case auxiliary(Mood, Tense)      // auxiliary in this tense + participle
        case werden(Mood, Tense)         // werden (or würde) in this tense + infinitive
        case futur2                      // werden + participle + auxiliary infinitive
    }

    static let germanCompound: [(Mood, Tense, GermanBuild)] = [
        (.ind, .perf, .auxiliary(.ind, .pres)), (.ind, .pqp, .auxiliary(.ind, .prat)),
        (.ind, .fut1, .werden(.ind, .pres)), (.ind, .fut2, .futur2),
        (.k2, .wuerde, .werden(.k2, .prat)), (.k2, .pqp, .auxiliary(.k2, .prat)),
    ]

    func germanTable(_ entry: Entry) -> ConjugationTable {
        var byTag: [String: String] = [:]
        for f in content.forms(of: entry.id) where !f.tag.isEmpty && byTag[f.tag] == nil {
            byTag[f.tag] = f.form
        }
        let infinitive = entry.headword
        let particle = Self.separableParticle(infinitive: infinitive, zuInfinitive: byTag["inf.zu"])
        let base = particle.map { String(infinitive.dropFirst($0.count)) } ?? infinitive

        var blocks: [TenseBlock] = []
        for (mood, tense) in Self.germanSimple {
            let persons: [Person] = mood == .imp ? [.s2, .p2] : Person.allCases
            let forms: [ConjugatedForm] = persons.compactMap { person in
                let tag = FormTag(mood: mood, tense: tense, person: person)
                guard let joined = byTag[tag.description] else { return nil }
                let bare = particle.flatMap { p in joined.hasPrefix(p) ? String(joined.dropFirst(p.count)) : nil } ?? joined
                let text = particle.map { "\(bare) \($0)" } ?? joined
                let regular = GermanRegularConjugator.forms(infinitive: base, tag: tag).contains(bare.lowercased())
                return ConjugatedForm(tag: tag, text: text, isIrregular: !regular)
            }
            if !forms.isEmpty { blocks.append(TenseBlock(mood: mood, tense: tense, forms: forms, language: .de)) }
        }

        let participle = byTag["part.pass"]
        let auxName = entry.auxiliary ?? "haben"
        // Verbs that take either mostly move (fahren, fliegen); their tables show sein.
        let aux: Auxiliary = auxName == "haben" ? .haben : .sein
        let auxTable = verbForms(aux.infinitive)
        let werden = verbForms("werden")
        for (mood, tense, build) in Self.germanCompound {
            let forms: [ConjugatedForm] = Person.allCases.compactMap { person in
                let tag = FormTag(mood: mood, tense: tense, person: person, auxiliary: auxName == "both" ? aux : nil)
                let text: String?
                switch build {
                case .auxiliary(let m, let t):
                    text = participle.flatMap { part in
                        auxTable[FormTag(mood: m, tense: t, person: person).description].map { "\($0) \(part)" }
                    }
                case .werden(let m, let t):
                    text = werden[FormTag(mood: m, tense: t, person: person).description].map { "\($0) \(infinitive)" }
                case .futur2:
                    text = participle.flatMap { part in
                        werden[FormTag(mood: .ind, tense: .pres, person: person).description]
                            .map { "\($0) \(part) \(aux.infinitive)" }
                    }
                }
                return text.map { ConjugatedForm(tag: tag, text: $0, isIrregular: false) }
            }
            if !forms.isEmpty { blocks.append(TenseBlock(mood: mood, tense: tense, forms: forms, language: .de)) }
        }
        return ConjugationTable(lemmaID: entry.id, infinitive: infinitive, auxiliary: entry.auxiliary,
                                participle: participle, gerund: nil, blocks: blocks)
    }

    /// The separable particle of a German verb, read off its zu-infinitive: anzurufen -> an. Inseparable
    /// verbs write zu apart (zu besuchen), which the dictionary doesn't keep, so they have none.
    static func separableParticle(infinitive: String, zuInfinitive: String?) -> String? {
        guard let zu = zuInfinitive, !zu.contains(" ") else { return nil }
        let inf = Array(infinitive), z = Array(zu)
        guard z.count == inf.count + 2 else { return nil }
        for i in 1..<inf.count where Array(z[i..<(i + 2)]) == ["z", "u"] {
            if Array(z[..<i]) == Array(inf[..<i]) && Array(z[(i + 2)...]) == Array(inf[i...]) {
                return String(inf[..<i])
            }
        }
        return nil
    }
}

/// Regular (weak) German paradigms, used to mark irregular forms in verb tables. A form counts as regular
/// if the weak pattern produces it: machen, machte, gemacht. Strong verbs (gehen, ging) are irregular.
public enum GermanRegularConjugator {
    public static func forms(infinitive: String, tag: FormTag) -> Set<String> {
        let inf = infinitive.lowercased()
        let stem: String
        if inf.hasSuffix("en") {
            stem = String(inf.dropLast(2))
        } else if inf.hasSuffix("ln") || inf.hasSuffix("rn") {
            stem = String(inf.dropLast())
        } else {
            return []
        }
        guard !stem.isEmpty, let person = tag.person else { return [] }
        // arbeiten, rechnen: an e before st and t.
        let e = stem.hasSuffix("t") || stem.hasSuffix("d") || stem.hasSuffix("chn") || stem.hasSuffix("tm")
            || stem.hasSuffix("gn") || stem.hasSuffix("dn") ? "e" : ""
        let sibilant = ["s", "ß", "z", "x"].contains { stem.hasSuffix($0) }
        let i = Person.allCases.firstIndex(of: person) ?? 0
        switch (tag.mood, tag.tense) {
        case (.ind, .pres):
            let second = sibilant ? stem + "t" : stem + e + "st"
            return [[stem + "e", second, stem + e + "t", inf, stem + e + "t", inf][i]]
        case (.ind, .prat), (.k2, .prat):
            let past = stem + e + "te"
            return [[past, past + "st", past, past + "n", past + "t", past + "n"][i]]
        case (.k1, .pres):
            return [[stem + "e", stem + "est", stem + "e", stem + "en", stem + "et", stem + "en"][i]]
        case (.imp, .pres):
            return person == .s2 ? [stem, stem + "e"] : [stem + e + "t"]
        default:
            return []
        }
    }
}
