import Foundation
import ItalianCore

/// Regular paradigms for -are, -ere and -ire verbs, used to mark irregular forms in verb tables
/// (HANDOFF.md 3.3: irregular forms in bold orange). A form counts as regular if any regular
/// pattern produces it, so -isc- verbs and both -ire patterns are regular.
public enum RegularConjugator {
    public static func forms(infinitive: String, tag: FormTag) -> Set<String> {
        let inf = infinitive.lowercased()
        guard inf.count > 3 else { return [] }
        let ending = String(inf.suffix(3))
        let stem = String(inf.dropLast(3))
        switch ending {
        case "are": return are(stem: stem, tag: tag)
        case "ere": return ere(stem: stem, tag: tag)
        case "ire": return ire(stem: stem, tag: tag)
        default: return []
        }
    }

    private static func idx(_ p: Person?) -> Int {
        guard let p else { return 0 }
        return Person.allCases.firstIndex(of: p) ?? 0
    }

    /// -care/-gare keep the hard sound before e and i (cerchi, pagherò); -ciare/-giare drop the i (mangi, mangerò).
    private static func soft(_ stem: String, before vowel: Character) -> String {
        guard vowel == "e" || vowel == "i" else { return stem }
        if stem.hasSuffix("c") || stem.hasSuffix("g") { return stem + "h" }
        if stem.hasSuffix("ci") || stem.hasSuffix("gi") || stem.hasSuffix("sci") { return String(stem.dropLast()) }
        if stem.hasSuffix("i") && vowel == "i" { return String(stem.dropLast()) }  // studiare: studi
        return stem
    }

    private static func join(_ stem: String, _ ending: String) -> String {
        guard let first = ending.first else { return stem }
        return soft(stem, before: first) + ending
    }

    static func are(stem: String, tag: FormTag) -> Set<String> {
        let i = idx(tag.person)
        let e: [String]
        switch tag.tenseKey {
        case "ind.pres": e = ["o", "i", "a", "iamo", "ate", "ano"]
        case "ind.impf": e = ["avo", "avi", "ava", "avamo", "avate", "avano"]
        case "ind.prem": e = ["ai", "asti", "ò", "ammo", "aste", "arono"]
        case "ind.fut": e = ["erò", "erai", "erà", "eremo", "erete", "eranno"]
        case "cond.pres": e = ["erei", "eresti", "erebbe", "eremmo", "ereste", "erebbero"]
        case "sub.pres": e = ["i", "i", "i", "iamo", "iate", "ino"]
        case "sub.impf": e = ["assi", "assi", "asse", "assimo", "aste", "assero"]
        case "imp.pres": e = ["", "a", "i", "iamo", "ate", "ino"]
        case "imp.neg": return [stem + "are"]
        case "inf.pres": return [stem + "are"]
        case "ger.pres": return [stem + "ando"]
        case "part.pass": return [stem + "ato"]
        case "part.pres": return [stem + "ante"]
        default: return []
        }
        return [join(stem, e[i])]
    }

    static func ere(stem: String, tag: FormTag) -> Set<String> {
        let i = idx(tag.person)
        let e: [String]
        switch tag.tenseKey {
        case "ind.pres": e = ["o", "i", "e", "iamo", "ete", "ono"]
        case "ind.impf": e = ["evo", "evi", "eva", "evamo", "evate", "evano"]
        case "ind.prem":
            let a = ["ei", "esti", "é", "emmo", "este", "erono"][i]
            let b = ["etti", "esti", "ette", "emmo", "este", "ettero"][i]
            return [stem + a, stem + b]
        case "ind.fut": e = ["erò", "erai", "erà", "eremo", "erete", "eranno"]
        case "cond.pres": e = ["erei", "eresti", "erebbe", "eremmo", "ereste", "erebbero"]
        case "sub.pres": e = ["a", "a", "a", "iamo", "iate", "ano"]
        case "sub.impf": e = ["essi", "essi", "esse", "essimo", "este", "essero"]
        case "imp.pres": e = ["", "i", "a", "iamo", "ete", "ano"]
        case "imp.neg": return [stem + "ere"]
        case "inf.pres": return [stem + "ere"]
        case "ger.pres": return [stem + "endo"]
        case "part.pass": return [stem + "uto"]
        case "part.pres": return [stem + "ente"]
        default: return []
        }
        return [stem + e[i]]
    }

    static func ire(stem: String, tag: FormTag) -> Set<String> {
        let i = idx(tag.person)
        switch tag.tenseKey {
        case "ind.pres":
            return [stem + ["o", "i", "e", "iamo", "ite", "ono"][i],
                    stem + ["isco", "isci", "isce", "iamo", "ite", "iscono"][i]]
        case "sub.pres":
            return [stem + ["a", "a", "a", "iamo", "iate", "ano"][i],
                    stem + ["isca", "isca", "isca", "iamo", "iate", "iscano"][i]]
        case "imp.pres":
            return [stem + ["", "i", "a", "iamo", "ite", "ano"][i],
                    stem + ["", "isci", "isca", "iamo", "ite", "iscano"][i]]
        case "ind.impf": return [stem + ["ivo", "ivi", "iva", "ivamo", "ivate", "ivano"][i]]
        case "ind.prem": return [stem + ["ii", "isti", "ì", "immo", "iste", "irono"][i]]
        case "ind.fut": return [stem + ["irò", "irai", "irà", "iremo", "irete", "iranno"][i]]
        case "cond.pres": return [stem + ["irei", "iresti", "irebbe", "iremmo", "ireste", "irebbero"][i]]
        case "sub.impf": return [stem + ["issi", "issi", "isse", "issimo", "iste", "issero"][i]]
        case "imp.neg", "inf.pres": return [stem + "ire"]
        case "ger.pres": return [stem + "endo"]
        case "part.pass": return [stem + "ito"]
        case "part.pres": return [stem + "ente", stem + "iente"]
        default: return []
        }
    }
}
