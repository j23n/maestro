import Foundation
import PackKit

/// Open answers (HANDOFF.md 3.9): patterns with `(optional)` words and `{a|b}` choices, nestable, the
/// syntax tools/maestro_content/patterns.py checks at build time.
///
///     {Volentieri|Con piacere}!     Volentieri!  Con piacere!
///     Credo di sì(, perché)?        Credo di sì?  Credo di sì, perché?
public enum PatternGrader {
    /// More than this many answers from one pattern and the rest are dropped; the build keeps patterns
    /// below it.
    public static let maxVariants = 256

    private indirect enum Part {
        case text(String)
        case optional([[Part]])
        case choice([[Part]])
    }

    /// Every answer a pattern accepts, spaces collapsed. A pattern that doesn't parse accepts itself.
    public static func expand(_ pattern: String) -> [String] {
        var index = pattern.startIndex
        guard let alternatives = parse(pattern, &index, closer: nil) else { return [pattern] }
        var seen: [String] = []
        for alt in alternatives {
            for v in expand(alt) {
                let tidy = tidy(v)
                if !tidy.isEmpty && !seen.contains(tidy) { seen.append(tidy) }
            }
        }
        return seen
    }

    /// A typed answer against a drill's patterns, with a gap's accent tolerance.
    public static func grade(_ answer: String, patterns: [String], german: Bool) -> Grade {
        let accepted = patterns.flatMap { expand($0) }
        guard !accepted.isEmpty else { return .wrong(hint: "Type an answer first.") }
        let grade = DrillGrader.grade(answer, accepting: accepted, german: german)
        guard case .wrong = grade else { return grade }
        if DrillGrader.normalize(answer).isEmpty { return .wrong(hint: "Type an answer first.") }
        return .wrong(hint: "Not quite. Try it another way, or look at the English again.")
    }

    // MARK: Parsing

    private static func parse(_ s: String, _ i: inout String.Index, closer: Character?) -> [[Part]]? {
        var alternatives: [[Part]] = [[]]
        var buffer = ""
        func flush() {
            if !buffer.isEmpty { alternatives[alternatives.count - 1].append(.text(buffer)); buffer = "" }
        }
        while i < s.endIndex {
            let c = s[i]
            switch c {
            case "(", "{":
                flush()
                i = s.index(after: i)
                guard let inner = parse(s, &i, closer: c == "(" ? ")" : "}") else { return nil }
                alternatives[alternatives.count - 1].append(c == "(" ? .optional(inner) : .choice(inner))
                continue
            case ")", "}":
                guard c == closer else { return nil }
                flush()
                i = s.index(after: i)
                return alternatives
            case "|" where closer != nil:
                flush()
                alternatives.append([])
            default:
                buffer.append(c)
            }
            i = s.index(after: i)
        }
        guard closer == nil else { return nil }
        flush()
        return alternatives
    }

    private static func expand(_ parts: [Part]) -> [String] {
        var out = [""]
        for part in parts {
            let choices: [String]
            switch part {
            case .text(let t): choices = [t]
            case .choice(let alts): choices = alts.flatMap { expand($0) }
            case .optional(let alts): choices = [""] + alts.flatMap { expand($0) }
            }
            out = out.flatMap { a in choices.map { a + $0 } }
            if out.count > maxVariants { out = Array(out.prefix(maxVariants)) }
        }
        return out
    }

    private static func tidy(_ s: String) -> String {
        var t = s.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        for p in [",", ".", "!", "?"] { t = t.replacingOccurrences(of: " " + p, with: p) }
        return t
    }
}
