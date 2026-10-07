import Foundation

/// Grades the short English answers of relay tasks (docs/05 § Other graders, docs/06 § Relay).
///
/// - `time`: finds `HH:MM`, `HH.MM` or `HH MM` and also accepts the hour ± 12 (*10:15* for 22:15). For a time on
///   the hour, a bare hour also counts (*9*, *9 pm*, *nine o'clock* for 21:00).
/// - `price`: finds a decimal with `,` or `.`; a whole number (in digits or words) counts too; within 0.001;
///   currency words are ignored.
/// - `number`: finds an integer, in digits or English words (*3*, *three*, *twenty-one*).
/// - `text`: any accepted phrase occurs as a token subsequence (in order, gaps allowed), ignoring case and
///   punctuation.
public enum EnglishAnswerGrader {
    public enum Answer: Sendable, Hashable {
        case time(hour: Int, minute: Int)
        case price(Double)
        case number(Int)
        case text([String])
    }

    public static let priceTolerance = 0.001

    public static func isCorrect(_ response: String, answer: Answer) -> Bool {
        switch answer {
        case .time(let hour, let minute):
            let numbers = extract(response)
            func sameHour(_ h: Int) -> Bool { h == hour || h + 12 == hour || h - 12 == hour }
            if numbers.times.contains(where: { $0.minute == minute && sameHour($0.hour) }) { return true }
            return minute == 0 && numbers.wholeNumbers.contains { $0 <= 24 && sameHour($0) }
        case .price(let value):
            let numbers = extract(response)
            let values = numbers.decimals + numbers.wholeNumbers.map(Double.init)
            return values.contains { abs($0 - value) <= priceTolerance + 1e-9 }
        case .number(let value):
            let numbers = extract(response)
            return numbers.wholeNumbers.contains(value) || numbers.decimals.contains(Double(value))
        case .text(let phrases):
            let tokens = englishTokens(response)
            return phrases.contains { isSubsequence(englishTokens($0), of: tokens) }
        }
    }

    public static func grade(_ response: String, answer: Answer) -> GradedAnswer {
        GradedAnswer(outcome: isCorrect(response, answer: answer) ? .correct : .wrong)
    }

    // MARK: - Extraction

    struct Numbers {
        /// `HH:MM`, `HH.MM`, `HH MM`.
        var times: [(hour: Int, minute: Int)] = []
        /// Numbers with a decimal separator (`1,60`, `1.6`); a two-digit decimal also reads as a time.
        var decimals: [Double] = []
        /// Integers in digits that are not part of a time or a decimal, and English number words.
        var wholeNumbers: [Int] = []
    }

    /// Runs of ASCII digits with their positions.
    private static func digitRuns(_ chars: [Character]) -> [(start: Int, end: Int, value: String)] {
        var runs: [(Int, Int, String)] = []
        var i = 0
        while i < chars.count {
            guard chars[i].isASCII, chars[i].isNumber else {
                i += 1
                continue
            }
            let start = i
            while i < chars.count, chars[i].isASCII, chars[i].isNumber { i += 1 }
            runs.append((start, i, String(chars[start..<i])))
        }
        return runs
    }

    static func extract(_ text: String) -> Numbers {
        let chars = Array(text)
        let runs = digitRuns(chars)
        var numbers = Numbers()
        var used = Set<Int>()
        for n in runs.indices.dropLast() {
            let a = runs[n]
            let b = runs[n + 1]
            guard b.start == a.end + 1 else { continue }
            let separator = chars[a.end]
            // HH:MM, HH.MM, HH MM: a 1–2 digit hour, one separator, exactly two minute digits.
            if [":", ".", " "].contains(separator), a.value.count <= 2, b.value.count == 2, let h = Int(a.value),
                let m = Int(b.value), h <= 24, m <= 59
            {
                numbers.times.append((h, m))
                used.formUnion([n, n + 1])
            }
            if [",", "."].contains(separator), let value = Double(a.value + "." + b.value) {
                numbers.decimals.append(value)
                used.formUnion([n, n + 1])
            }
        }
        for (n, run) in runs.enumerated() where !used.contains(n) {
            if let value = Int(run.value) { numbers.wholeNumbers.append(value) }
        }
        numbers.wholeNumbers += englishNumberWords(englishTokens(text))
        return numbers
    }

    private static let unitWords: [String: Int] = [
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
        "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
        "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    ]
    private static let tensWords: [String: Int] = [
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
        "ninety": 90,
    ]

    /// English number words 0–99: *three*, *twenty*, *twenty-one*, *twenty one*.
    static func englishNumberWords(_ tokens: [String]) -> [Int] {
        var result: [Int] = []
        var i = 0
        while i < tokens.count {
            if let tens = tensWords[tokens[i]] {
                if i + 1 < tokens.count, let unit = unitWords[tokens[i + 1]], (1...9).contains(unit) {
                    result.append(tens + unit)
                    i += 2
                    continue
                }
                result.append(tens)
            } else if let unit = unitWords[tokens[i]] {
                result.append(unit)
            }
            i += 1
        }
        return result
    }

    /// Lowercase words; punctuation (other than apostrophes inside words) separates them.
    static func englishTokens(_ text: String) -> [String] {
        var tokens: [String] = []
        var current = ""
        for c in text.lowercased() {
            let mapped: Character = Normalizer.apostropheVariants.contains(c) ? "'" : c
            if mapped.isLetter || mapped.isNumber || (mapped == "'" && !current.isEmpty) {
                current.append(mapped)
            } else if !current.isEmpty {
                tokens.append(current)
                current = ""
            }
        }
        if !current.isEmpty { tokens.append(current) }
        return tokens.map { $0.hasSuffix("'") ? String($0.dropLast()) : $0 }
    }

    static func isSubsequence(_ needle: [String], of haystack: [String]) -> Bool {
        guard !needle.isEmpty else { return false }
        var i = 0
        for token in haystack where i < needle.count && token == needle[i] { i += 1 }
        return i == needle.count
    }
}
