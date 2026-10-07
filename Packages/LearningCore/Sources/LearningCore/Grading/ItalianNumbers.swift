import Foundation

/// Italian number words for grading (docs/05 § Speech transcripts, `{NUMBER}` slots): integers 0–9999 to words
/// and back, prices (`6,20 €` → *sei euro e venti*) and clock times (`10:15` → *dieci e quindici*, 24-hour
/// style as in *alle quindici e trenta*). These are grading rules, not course content (the time cues and the
/// article forms below are how digits are read, like the number words themselves).
public enum ItalianNumbers {
    public static let range = 0...9999

    private static let units = [
        "zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci", "undici", "dodici",
        "tredici", "quattordici", "quindici", "sedici", "diciassette", "diciotto", "diciannove",
    ]
    private static let tens = [
        "", "", "venti", "trenta", "quaranta", "cinquanta", "sessanta", "settanta", "ottanta", "novanta",
    ]

    /// `n` in words, 0–9999: *ventuno*, *ventotto*, *ventitré*, *cento*, *centouno*, *centotto*, *centottanta*,
    /// *mille*, *duemila*. Nil outside the range.
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
        // Cento drops its final vowel before otto and ottanta: centotto, centottanta, duecentottanta.
        if hundreds > 0, rest == 8 || rest / 10 == 8 { s.removeLast() }
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
    /// *ventun*, the elided *centuno* and the full *centootto*, *centoottanta*.
    private static let lexicon: [String: Int] = {
        var map: [String: Int] = ["un": 1, "una": 1]
        for n in range {
            guard let w = words(n) else { continue }
            var spellings = [Normalizer.stripAccents(w)]
            for (from, to) in [("centou", "centu"), ("centott", "centoott")] {
                let variant = spellings[0].replacingOccurrences(of: from, with: to)
                if variant != spellings[0] { spellings.append(variant) }
            }
            for s in spellings where n > 1 && s.hasSuffix("uno") { spellings.append(String(s.dropLast())) }
            for s in spellings where map[s] == nil { map[s] = n }
        }
        return map
    }()

    /// What a digit `1` before a word may stand for: the indefinite article, whose form depends on the noun
    /// (`1 caffè` is *un caffè*, `1 spremuta` *una spremuta*), or *uno*. `spellOut` leaves such a `1` as it is and
    /// the matchers accept it for any of these (`matchesSpoken(expected:heard:)`).
    public static let articleOne: Set<String> = ["un", "uno", "una", "un'"]

    /// Words after which a number is a clock time: `alle 15.30` is *alle quindici e trenta*, `all'1` *all'una*.
    public static let timeCues: Set<String> = [
        "alle", "all'", "dalle", "dall'", "delle", "dell'", "sulle", "sull'", "le", "l'", "ore", "verso", "entro",
    ]

    /// Whether a heard token (after `spellOut` and normalising) matches an expected token: equal, or a `1` that
    /// `spellOut` kept before a word standing for *un*, *uno*, *una* or *un'*.
    public static func matchesSpoken(expected: String, heard: String) -> Bool {
        expected == heard || (heard == "1" && articleOne.contains(expected))
    }

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
    /// `10:15` → *dieci e quindici*, `alle 15.30` → *alle quindici e trenta*, `30` → *trenta*. Digits glued to
    /// letters (`A1`, `3a`, `3pm`, `1º`, `20°`) and numbers above 9999 stay; so does a `1` before a word (`1 caffè`),
    /// which stands for an article of unknown gender (`articleOne`). An `H.MM` with no currency and no time cue
    /// before it is read as a price here; `spellOutReadings` gives the time reading too.
    public static func spellOut(_ text: String) -> String {
        render(text, dottedAsTime: false).text
    }

    /// Every reading of `text` (`spellOut` first): two when an `H.MM` could be a price or a time (`6.20` →
    /// *sei euro e venti* and *sei e venti*), else one. The matchers accept either.
    public static func spellOutReadings(_ text: String) -> [String] {
        let price = render(text, dottedAsTime: false)
        guard price.ambiguous else { return [price.text] }
        let time = render(text, dottedAsTime: true).text
        return time == price.text ? [price.text] : [price.text, time]
    }

    /// Ordinal and degree marks that keep the digits before them as they are (`1º maggio`, `20°`).
    private static let ordinalMarks: Set<Character> = ["º", "ª", "°"]

    private static func render(_ text: String, dottedAsTime: Bool) -> (text: String, ambiguous: Bool) {
        let chars = Array(text)
        var out = ""
        var ambiguous = false
        var i = 0
        while i < chars.count {
            let c = chars[i]
            let startsNumber =
                isDigit(c) || (c == "€" && nextNonSpace(chars, from: i + 1).map { isDigit(chars[$0]) } == true)
            if startsNumber, !(i > 0 && chars[i - 1].isLetter),
                let read = readNumber(chars, at: i, afterTimeCue: isTimeCue(wordBefore(chars, i)))
            {
                let after = read.end < chars.count ? chars[read.end] : " "
                if !after.isLetter, !ordinalMarks.contains(after) {
                    let reading = read.ambiguousTime.map { dottedAsTime ? $0 : read.words } ?? read.words
                    if read.ambiguousTime != nil { ambiguous = true }
                    out += " " + reading + " "
                    i = read.end
                    continue
                }
            }
            if isDigit(c) {
                // A number we leave alone (glued to a word, out of range, an odd decimal): copy it whole,
                // separators between digits included, so its parts are not converted one by one.
                while i < chars.count,
                    isDigit(chars[i]) || chars[i].isLetter || ordinalMarks.contains(chars[i])
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
        return (out.split(separator: " ", omittingEmptySubsequences: true).joined(separator: " "), ambiguous)
    }

    /// The word just before index `i` (spaces skipped), lowercased, apostrophes unified: `all'` in `all'1`.
    private static func wordBefore(_ chars: [Character], _ i: Int) -> String {
        var j = i - 1
        while j >= 0, chars[j] == " " { j -= 1 }
        var word: [Character] = []
        while j >= 0, chars[j].isLetter || chars[j] == "'" || Normalizer.apostropheVariants.contains(chars[j]) {
            word.append(Normalizer.apostropheVariants.contains(chars[j]) ? "'" : chars[j])
            j -= 1
        }
        return String(word.reversed()).lowercased()
    }

    private static func isTimeCue(_ word: String) -> Bool { timeCues.contains(word) }

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

    /// What `readNumber` found: its words, the index after it, and for an `H.MM` that could be a price or a
    /// time, the time reading (`words` holds the price reading).
    private struct Read {
        let words: String
        let end: Int
        var ambiguousTime: String?
    }

    /// Reads `[€] digits [sep digits] [€ | euro]` at `start`. After a time cue, `H.MM` and a bare hour are a time.
    private static func readNumber(_ chars: [Character], at start: Int, afterTimeCue: Bool) -> Read? {
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
        let time = sep != "," && !currency && whole.count <= 2 && fraction.count == 2
            ? Int(fraction).flatMap { timeWords(hour: value, minute: $0) } : nil
        switch sep {
        case ":":
            return time.map { Read(words: $0, end: j) }
        case ",", ".":
            if sep == ".", afterTimeCue, let time { return Read(words: time, end: j) }
            if fraction.count == 2 || (fraction.count == 1 && currency), let cents = Int(fraction),
                let price = priceWords(euros: value, cents: fraction.count == 1 ? cents * 10 : cents)
            {
                // No currency and no time cue: `6.20` may be a price or a time; the matchers try both.
                return Read(words: price, end: end, ambiguousTime: sep == "." ? time : nil)
            }
            if sep == ".", fraction.count == 3, whole.count <= 3, let low = Int(fraction) {
                let n = value * 1000 + low
                if currency { return priceWords(euros: n, cents: 0).map { Read(words: $0, end: end) } }
                return words(n).map { Read(words: $0, end: j) }
            }
            return nil
        default:
            if currency { return priceWords(euros: value, cents: 0).map { Read(words: $0, end: end) } }
            if afterTimeCue, let hour = timeWords(hour: value, minute: 0) { return Read(words: hour, end: j) }
            // A 1 before a word is an article whose form we can't know: keep the digit (`articleOne`).
            if value == 1, j < chars.count, chars[j] == " ", let next = nextNonSpace(chars, from: j),
                chars[next].isLetter
            {
                return Read(words: "1", end: j)
            }
            return words(value).map { Read(words: $0, end: j) }
        }
    }
}
