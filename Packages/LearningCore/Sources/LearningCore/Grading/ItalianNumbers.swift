import Foundation

/// Italian number words for grading (docs/05 § Speech transcripts, `{NUMBER}` slots): integers 0–9999 to words
/// and back, prices (`6,20 €` → *sei euro e venti*) and clock times (`10:15` → *dieci e quindici*, 24-hour
/// style as in *alle quindici e trenta*). These are grading rules, not course content.
public enum ItalianNumbers {
    public static let range = 0...9999

    private static let units = [
        "zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci", "undici", "dodici",
        "tredici", "quattordici", "quindici", "sedici", "diciassette", "diciotto", "diciannove",
    ]
    private static let tens = [
        "", "", "venti", "trenta", "quaranta", "cinquanta", "sessanta", "settanta", "ottanta", "novanta",
    ]

    /// `n` in words, 0–9999: *ventuno*, *ventotto*, *ventitré*, *cento*, *centouno*, *mille*, *duemila*. Nil
    /// outside the range.
    public static func words(_ n: Int) -> String? {
        guard range.contains(n) else { return nil }
        if n == 0 { return units[0] }
        let thousands = n / 1000
        let rest = n % 1000
        var s = ""
        if thousands == 1 { s = "mille" } else if thousands > 1 { s = units[thousands] + "mila" }
        if rest > 0 { s += below1000(rest) }
        // A final "tre" in a compound takes the accent: ventitré, centotré, milletré.
        if n > 3, s.hasSuffix("tre") { s = String(s.dropLast(3)) + "tré" }
        return s
    }

    private static func below1000(_ n: Int) -> String {
        let hundreds = n / 100
        let rest = n % 100
        var s = ""
        if hundreds == 1 { s = "cento" } else if hundreds > 1 { s = units[hundreds] + "cento" }
        if rest > 0 { s += below100(rest) }
        return s
    }

    private static func below100(_ n: Int) -> String {
        if n < 20 { return units[n] }
        let t = tens[n / 10]
        let u = n % 10
        if u == 0 { return t }
        // The tens drop their final vowel before uno and otto: ventuno, ventotto, trentuno.
        if u == 1 || u == 8 { return String(t.dropLast()) + units[u] }
        return t + units[u]
    }

    /// Every accepted spelling (accents stripped) → value. Besides `words(_:)`: *un*/*una* for 1, the truncated
    /// *ventun*, and the elided hundreds *centuno*, *centotto*, *centottanta*.
    private static let lexicon: [String: Int] = {
        var map: [String: Int] = ["un": 1, "una": 1]
        for n in range {
            guard let w = words(n) else { continue }
            var spellings = [Normalizer.stripAccents(w)]
            let elided = spellings[0].replacingOccurrences(of: "centou", with: "centu")
                .replacingOccurrences(of: "centoo", with: "cento")
            if elided != spellings[0] { spellings.append(elided) }
            for s in spellings where n > 1 && s.hasSuffix("uno") { spellings.append(String(s.dropLast())) }
            for s in spellings where map[s] == nil { map[s] = n }
        }
        return map
    }()

    /// The value of one token: digits (`30`) or an Italian number word, case- and accent-insensitive (`trenta`,
    /// `ventitre`, `centotto`). Nil for anything else.
    public static func integerValue(of token: String) -> Int? {
        if !token.isEmpty, token.allSatisfy({ $0.isASCII && $0.isNumber }) { return Int(token) }
        return lexicon[Normalizer.stripAccents(token.lowercased())]
    }

    /// A price in words: `(6, 20)` → *sei euro e venti*, `(1, 60)` → *un euro e sessanta*, `(3, 0)` → *tre euro*,
    /// `(0, 50)` → *cinquanta centesimi*.
    public static func priceWords(euros: Int, cents: Int) -> String? {
        guard euros >= 0, (0...99).contains(cents), let e = words(euros), let c = words(cents) else { return nil }
        if euros == 0 { return cents == 1 ? "un centesimo" : (cents == 0 ? "zero euro" : c + " centesimi") }
        let euroPart = euros == 1 ? "un euro" : e + " euro"
        return cents == 0 ? euroPart : euroPart + " e " + c
    }

    /// A clock time in words: `(10, 15)` → *dieci e quindici*, `(13, 30)` → *tredici e trenta*, `(1, 0)` → *una*.
    public static func timeWords(hour: Int, minute: Int) -> String? {
        guard (0...24).contains(hour), (0...59).contains(minute), let h = words(hour), let m = words(minute) else {
            return nil
        }
        let hourWord = hour == 1 ? "una" : h
        return minute == 0 ? hourWord : hourWord + " e " + m
    }

    /// Converts the digits, prices and times in a raw transcript into Italian words, before normalising
    /// (docs/05 § Speech transcripts, step 1): `6,20 €` and `€ 6.20` → *sei euro e venti*, `3 euro` → *tre euro*,
    /// `10:15` → *dieci e quindici*, `30` → *trenta*. Digits glued to letters (`A1`) and numbers above 9999 stay.
    public static func spellOut(_ text: String) -> String {
        let chars = Array(text)
        var out = ""
        var i = 0
        while i < chars.count {
            let c = chars[i]
            let startsNumber =
                isDigit(c) || (c == "€" && nextNonSpace(chars, from: i + 1).map { isDigit(chars[$0]) } == true)
            if startsNumber, !(i > 0 && chars[i - 1].isLetter), let (words, end) = readNumber(chars, at: i) {
                out += " " + words + " "
                i = end
                continue
            }
            if isDigit(c) {
                // A number we leave alone (glued to a word, out of range, an odd decimal): copy it whole,
                // separators between digits included, so its parts are not converted one by one.
                while i < chars.count,
                    isDigit(chars[i]) || chars[i].isLetter
                        || ([",", ".", ":"].contains(chars[i]) && i + 1 < chars.count && isDigit(chars[i + 1]))
                {
                    out.append(chars[i])
                    i += 1
                }
                continue
            }
            out.append(c)
            i += 1
        }
        return out.split(separator: " ", omittingEmptySubsequences: true).joined(separator: " ")
    }

    private static func isDigit(_ c: Character) -> Bool { c.isASCII && c.isNumber }

    private static func nextNonSpace(_ chars: [Character], from i: Int) -> Int? {
        var j = i
        while j < chars.count, chars[j] == " " { j += 1 }
        return j < chars.count ? j : nil
    }

    private static func readDigits(_ chars: [Character], _ j: inout Int) -> String {
        var s = ""
        while j < chars.count, isDigit(chars[j]) {
            s.append(chars[j])
            j += 1
        }
        return s
    }

    /// Reads `[€] digits [sep digits] [€ | euro]` at `start` and returns its words and the index after it.
    private static func readNumber(_ chars: [Character], at start: Int) -> (String, Int)? {
        var j = start
        var currency = false
        if chars[j] == "€" {
            currency = true
            j += 1
            while j < chars.count, chars[j] == " " { j += 1 }
        }
        let whole = readDigits(chars, &j)
        guard !whole.isEmpty, let value = Int(whole) else { return nil }
        var sep: Character?
        var fraction = ""
        if j + 1 < chars.count, [",", ".", ":"].contains(chars[j]), isDigit(chars[j + 1]) {
            sep = chars[j]
            var k = j + 1
            fraction = readDigits(chars, &k)
            j = k
        }
        // A trailing currency marker: "€" or the word "euro".
        var end = j
        if !currency || sep != ":" {
            var k = j
            while k < chars.count, chars[k] == " " { k += 1 }
            if k < chars.count, chars[k] == "€" {
                currency = true
                end = k + 1
            } else if k + 4 <= chars.count, String(chars[k..<(k + 4)]).lowercased() == "euro",
                k + 4 == chars.count || !chars[k + 4].isLetter
            {
                currency = true
                end = k + 4
            }
        }
        switch sep {
        case ":":
            guard !currency, whole.count <= 2, fraction.count == 2, let minute = Int(fraction),
                let words = timeWords(hour: value, minute: minute)
            else { return nil }
            return (words, j)
        case ",", ".":
            if fraction.count == 2 || (fraction.count == 1 && currency), let cents = Int(fraction) {
                let c = fraction.count == 1 ? cents * 10 : cents
                return priceWords(euros: value, cents: c).map { ($0, end) }
            }
            if sep == ".", fraction.count == 3, whole.count <= 3, let low = Int(fraction) {
                let n = value * 1000 + low
                if currency { return priceWords(euros: n, cents: 0).map { ($0, end) } }
                return words(n).map { ($0, j) }
            }
            return nil
        default:
            if currency { return priceWords(euros: value, cents: 0).map { ($0, end) } }
            return words(value).map { ($0, j) }
        }
    }
}
