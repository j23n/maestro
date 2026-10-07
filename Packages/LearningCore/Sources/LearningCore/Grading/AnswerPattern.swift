import Foundation

/// A slot in an answer pattern (docs/03 § The answer-pattern language).
public enum PatternSlot: String, Sendable, Hashable, CaseIterable, Codable {
    /// `{NAME}`: any 1–3 words.
    case name = "NAME"
    /// `{NUMBER}`: an integer in digits or Italian words (one token).
    case number = "NUMBER"
    /// `{ME.nationality}`: the learner's nationality in their gender form; any one word for "Another country".
    case nationality = "ME.nationality"
    /// `{ME.home}`: the country's home phrase (or one of its `alt_home_phrases`); any 1–4 words otherwise.
    case home = "ME.home"
    /// `{ME.country}`: the country's Italian name; any 1–4 words for "Another country".
    case country = "ME.country"

    /// How the slot is written in a pattern and shown in an unfilled expansion: `{NAME}`.
    public var placeholder: String { "{\(rawValue)}" }

    /// How many response words an unfilled slot may stand for.
    public var wordRange: ClosedRange<Int> {
        switch self {
        case .name: 1...3
        case .number, .nationality: 1...1
        case .home, .country: 1...4
        }
    }

    /// True for the personal slots filled from the learner's onboarding answers.
    public var isPersonal: Bool { rawValue.hasPrefix("ME.") }

    /// Whether `words` (normalised response tokens) can fill this slot when it is matched as a wildcard.
    public func accepts<S: Collection>(_ words: S) -> Bool where S.Element == String {
        guard wordRange.contains(words.count) else { return false }
        if self == .number, let word = words.first { return ItalianNumbers.integerValue(of: word) != nil }
        return true
    }
}

/// An error in an answer pattern. `description` is the message the pipeline and tests compare.
public enum PatternError: Error, Equatable, Sendable, CustomStringConvertible {
    case unbalanced(String)
    case unexpected(Character, offset: Int)
    case danglingEscape
    case unknownSlot(String)
    case mixedGenderedAlternatives(String)
    case expansionLimit(limit: Int, count: Int)

    public var description: String {
        switch self {
        case .unbalanced(let what): "unbalanced \(what)"
        case .unexpected(let c, let offset): "unexpected '\(c)' at \(offset)"
        case .danglingEscape: "pattern ends with a lone backslash"
        case .unknownSlot(let name): "unknown slot {\(name)}"
        case .mixedGenderedAlternatives(let group): "every alternative needs m: or f:, or none does: {\(group)}"
        case .expansionLimit(let limit, let count): "expansion limit \(limit) exceeded (\(count))"
        }
    }
}

/// One string an answer pattern accepts, normalised (docs/03; `fixtures/grading/patterns.json`).
public struct PatternExpansion: Sendable, Hashable {
    /// The gender tag of an expansion that went through a `{m:…|f:…}` group (or a gendered `{ME.nationality}`).
    public enum Gender: String, Sendable, Hashable, Codable { case m, f }

    /// A slot that was not filled at expansion time, at its token index.
    public struct SlotPosition: Sendable, Hashable {
        public let tokenIndex: Int
        public let slot: PatternSlot
    }

    /// The expansion with the pattern syntax removed, in the author's case and punctuation (for display).
    public let raw: String
    /// Normalised tokens; an unfilled slot is one token, its placeholder (`{NAME}`).
    public let tokens: [String]
    /// Indices of focus tokens (`[…]`, or the whole of a cloze gap).
    public let focus: [Int]
    /// `m` or `f` when the expansion took a gendered alternative.
    public let gender: Gender?
    /// Slots left as wildcards, by token index.
    public let slots: [SlotPosition]
    /// The raw text around the slots, in the author's case and punctuation: `slots.count + 1` pieces (`Mi chiamo `
    /// and `.` for `Mi chiamo {NAME}.`). `raw` is them joined with the placeholders.
    let rawSegments: [String]

    /// The normalised text: tokens joined by single spaces (`mi chiamo {NAME}`).
    public var text: String { tokens.joined(separator: " ") }

    public func isFocus(_ tokenIndex: Int) -> Bool { focus.contains(tokenIndex) }

    public func slot(at tokenIndex: Int) -> PatternSlot? {
        slots.first { $0.tokenIndex == tokenIndex }?.slot
    }

    /// The raw text with each slot replaced by `fill(slotIndex)` (an index into `slots`), or by its placeholder when
    /// `fill` returns nil; spaces collapsed.
    func rawFilled(_ fill: (Int) -> String?) -> String {
        var text = rawSegments.first ?? ""
        for (n, position) in slots.enumerated() {
            text += fill(n) ?? position.slot.placeholder
            if n + 1 < rawSegments.count { text += rawSegments[n + 1] }
        }
        return AnswerPattern.collapseSpaces(text)
    }
}

/// An answer pattern: parser and expansion (docs/03 § The answer-pattern language).
///
/// Syntax: `{a|b}` alternatives (nestable), `(…)` optional, `[…]` focus, `{m:…|f:…}` gendered alternatives,
/// `{NAME}`, `{NUMBER}`, `{ME.nationality}`, `{ME.home}`, `{ME.country}` slots, and `\{ \[ \( \|` (any `\x`)
/// escapes. Expansion order: alternatives left to right, an optional group present before absent; the first
/// expansion is the model answer. A pattern may expand to at most `expansionLimit` strings; `init` throws beyond.
public struct AnswerPattern: Sendable, Hashable, CustomStringConvertible {
    public static let expansionLimit = 512

    /// The pattern as written.
    public let source: String
    let root: Node

    public var description: String { source }

    /// Parses `source` and checks the expansion limit.
    public init(_ source: String, limit: Int = AnswerPattern.expansionLimit) throws(PatternError) {
        var parser = Parser(source)
        let root = try parser.parsePattern()
        try self.init(source: source, root: root, limit: limit)
    }

    /// A cloze gap `[[…]]`: the gap's content is a pattern and every token of it is focus (docs/03).
    public static func clozeGap(_ content: String) throws(PatternError) -> AnswerPattern {
        var parser = Parser(content)
        let inner = try parser.parsePattern()
        return try AnswerPattern(source: content, root: .focus(inner), limit: expansionLimit)
    }

    /// The content of the first `[[…]]` gap in a cloze sentence (`Vorrei [[un]] cappuccino.` → `un`).
    public static func clozeGapContent(in text: String) -> String? {
        guard let open = text.range(of: "[["), let close = text.range(of: "]]", range: open.upperBound..<text.endIndex)
        else { return nil }
        return String(text[open.upperBound..<close.lowerBound])
    }

    init(source: String, root: Node, limit: Int) throws(PatternError) {
        self.source = source
        self.root = root
        let count = root.counts.total
        if count > limit { throw .expansionLimit(limit: limit, count: count) }
    }

    /// The number of expansions without personal substitution (what the 512 limit applies to).
    public var expansionCount: Int { root.counts.total }

    /// The slots the pattern uses, in order of first appearance.
    public var slots: [PatternSlot] {
        var seen: [PatternSlot] = []
        root.visitSlots { if !seen.contains($0) { seen.append($0) } }
        return seen
    }

    /// Every expansion in order. Without a profile (or with no country), personal slots stay wildcards;
    /// with a country, `{ME.home}`, `{ME.country}` and `{ME.nationality}` are filled in (docs/03 § Personal slots).
    /// Gendered expansions are all returned; `LearnerProfile.accepts(_:)` says which ones a learner may give.
    public func expansions(profile: LearnerProfile? = nil) -> [PatternExpansion] {
        let node = profile?.country.map { root.substituting($0) } ?? root
        return node.partials(focus: false).map { $0.expansion() }
    }

    /// The masculine and feminine forms that a `{m:…|f:…}` group (or a gendered `{ME.nationality}`) offers for the
    /// same word: *americano*/*americana*, *nato*/*nata*. Alternatives with the same number of tokens are paired
    /// word by word (`{m:il mio amico|f:la mia amica}` → *il*/*la*, *mio*/*mia*, *amico*/*amica*); otherwise every
    /// differing token of one is paired with every differing token of the other. The typed grader treats a pair as
    /// two forms of one item, so under strict forms *americana* for *americano* is an inflection error, never a typo
    /// (docs/05 § Typed answers), even when the pack's `forms` table doesn't list both.
    func genderFormPairs(profile: LearnerProfile? = nil) -> Set<FormPair> {
        let node = profile?.country.map { root.substituting($0) } ?? root
        var pairs = Set<FormPair>()
        node.collectGenderFormPairs(into: &pairs)
        return pairs
    }

    /// The first expansion: the model answer in normalised form (fixture key `first`).
    public func firstExpansion(profile: LearnerProfile? = nil) -> PatternExpansion? {
        expansions(profile: profile).first
    }
}

// MARK: - AST

extension AnswerPattern {
    struct GenderedOption: Sendable, Hashable {
        let gender: PatternExpansion.Gender
        let node: Node
    }

    indirect enum Node: Sendable, Hashable {
        case text(String)
        case sequence([Node])
        case choice([Node])
        case gendered([GenderedOption])
        case optional(Node)
        case focus(Node)
        case slot(PatternSlot)
    }
}

// MARK: - Parser

extension AnswerPattern {
    struct Parser {
        let chars: [Character]
        var i = 0

        init(_ source: String) { chars = Array(source) }

        mutating func parsePattern() throws(PatternError) -> Node {
            let node = try parseSequence(until: [])
            if i < chars.count { throw .unexpected(chars[i], offset: i) }
            return node
        }

        /// Parses until one of `terminators` (not consumed) or the end.
        mutating func parseSequence(until terminators: Set<Character>) throws(PatternError) -> Node {
            var nodes: [Node] = []
            var text = ""
            func flush() {
                if !text.isEmpty { nodes.append(.text(text)) }
                text = ""
            }
            while i < chars.count {
                let c = chars[i]
                if terminators.contains(c) { break }
                switch c {
                case "\\":
                    guard i + 1 < chars.count else { throw .danglingEscape }
                    text.append(chars[i + 1])
                    i += 2
                case "{":
                    flush()
                    nodes.append(try parseBraces())
                case "(":
                    flush()
                    i += 1
                    let inner = try parseSequence(until: [")"])
                    guard i < chars.count, chars[i] == ")" else { throw .unbalanced("(") }
                    i += 1
                    nodes.append(.optional(inner))
                case "[":
                    flush()
                    i += 1
                    let inner = try parseSequence(until: ["]"])
                    guard i < chars.count, chars[i] == "]" else { throw .unbalanced("[") }
                    i += 1
                    nodes.append(.focus(inner))
                case "}", ")", "]", "|":
                    throw .unexpected(c, offset: i)
                default:
                    text.append(c)
                    i += 1
                }
            }
            flush()
            return nodes.count == 1 ? nodes[0] : .sequence(nodes)
        }

        /// `{…}`: a slot, alternatives, or gendered alternatives. `i` points at `{`.
        mutating func parseBraces() throws(PatternError) -> Node {
            let open = i
            i += 1
            // A slot is written exactly `{NAME}`; anything slot-like that isn't one is an error, not a literal.
            var j = i
            while j < chars.count, !"{}|\\([".contains(chars[j]) { j += 1 }
            if j < chars.count, chars[j] == "}" {
                let name = String(chars[i..<j])
                if let slot = PatternSlot(rawValue: name) {
                    i = j + 1
                    return .slot(slot)
                }
                let looksLikeSlot =
                    name.hasPrefix("ME.")
                    || (!name.isEmpty && name.allSatisfy { ($0.isUppercase && $0.isASCII) || $0 == "_" })
                if looksLikeSlot { throw .unknownSlot(name) }
            }
            var options: [(gender: PatternExpansion.Gender?, node: Node)] = []
            while true {
                var gender: PatternExpansion.Gender?
                if i + 1 < chars.count, chars[i + 1] == ":", chars[i] == "m" || chars[i] == "f" {
                    gender = chars[i] == "m" ? .m : .f
                    i += 2
                }
                let node = try parseSequence(until: ["|", "}"])
                options.append((gender, node))
                guard i < chars.count else { throw .unbalanced("{") }
                let c = chars[i]
                i += 1
                if c == "}" { break }
            }
            let gendered = options.filter { $0.gender != nil }.count
            if gendered == 0 { return .choice(options.map(\.node)) }
            guard gendered == options.count else {
                throw .mixedGenderedAlternatives(String(chars[(open + 1)..<(i - 1)]))
            }
            return .gendered(options.compactMap { o in o.gender.map { GenderedOption(gender: $0, node: o.node) } })
        }
    }
}

// MARK: - Counting (without generating) and expansion

extension AnswerPattern.Node {
    /// Expansion counts split by gender tag: untagged, masculine, feminine. A combination that would take a
    /// masculine and a feminine alternative in the same expansion is not generated (one learner, one gender).
    struct Counts {
        var n: Int
        var m: Int
        var f: Int
        var total: Int { Self.add(Self.add(n, m), f) }

        static let one = Counts(n: 1, m: 0, f: 0)

        static func add(_ a: Int, _ b: Int) -> Int {
            let (r, o) = a.addingReportingOverflow(b)
            return o ? Int.max : r
        }

        static func mul(_ a: Int, _ b: Int) -> Int {
            let (r, o) = a.multipliedReportingOverflow(by: b)
            return o ? Int.max : r
        }

        static func + (a: Counts, b: Counts) -> Counts {
            Counts(n: add(a.n, b.n), m: add(a.m, b.m), f: add(a.f, b.f))
        }

        static func * (a: Counts, b: Counts) -> Counts {
            Counts(
                n: mul(a.n, b.n),
                m: add(add(mul(a.m, b.n), mul(a.n, b.m)), mul(a.m, b.m)),
                f: add(add(mul(a.f, b.n), mul(a.n, b.f)), mul(a.f, b.f)))
        }
    }

    var counts: Counts {
        switch self {
        case .text, .slot: return .one
        case .sequence(let nodes): return nodes.reduce(Counts.one) { $0 * $1.counts }
        case .choice(let nodes): return nodes.reduce(Counts(n: 0, m: 0, f: 0)) { $0 + $1.counts }
        case .optional(let node): return node.counts + .one
        case .focus(let node): return node.counts
        case .gendered(let options):
            return options.reduce(Counts(n: 0, m: 0, f: 0)) { sum, option in
                let c = option.node.counts
                switch option.gender {
                case .m: return sum + Counts(n: 0, m: Counts.add(c.n, c.m), f: 0)
                case .f: return sum + Counts(n: 0, m: 0, f: Counts.add(c.n, c.f))
                }
            }
        }
    }

    /// See `AnswerPattern.genderFormPairs(profile:)`.
    func collectGenderFormPairs(into pairs: inout Set<FormPair>) {
        switch self {
        case .text, .slot: break
        case .sequence(let nodes), .choice(let nodes):
            for node in nodes { node.collectGenderFormPairs(into: &pairs) }
        case .optional(let node), .focus(let node): node.collectGenderFormPairs(into: &pairs)
        case .gendered(let options):
            for option in options { option.node.collectGenderFormPairs(into: &pairs) }
            func words(_ gender: PatternExpansion.Gender) -> [[String]] {
                options.filter { $0.gender == gender }.flatMap { $0.node.partials(focus: false) }.prefix(64).map {
                    $0.expansion().tokens.filter { !($0.hasPrefix("{") && $0.hasSuffix("}")) }
                }
            }
            for m in words(.m) {
                for f in words(.f) {
                    if m.count == f.count {
                        for (a, b) in zip(m, f) where a != b { pairs.insert(FormPair(a, b)) }
                    } else {
                        let onlyM = Set(m).subtracting(f)
                        let onlyF = Set(f).subtracting(m)
                        for a in onlyM { for b in onlyF { pairs.insert(FormPair(a, b)) } }
                    }
                }
            }
        }
    }

    func visitSlots(_ visit: (PatternSlot) -> Void) {
        switch self {
        case .text: break
        case .slot(let slot): visit(slot)
        case .sequence(let nodes), .choice(let nodes):
            for node in nodes { node.visitSlots(visit) }
        case .optional(let node), .focus(let node): node.visitSlots(visit)
        case .gendered(let options):
            for option in options { option.node.visitSlots(visit) }
        }
    }

    /// Fills the personal slots from the learner's country (docs/03 § Personal slots).
    func substituting(_ country: LearnerProfile.Country) -> Self {
        switch self {
        case .text: return self
        case .slot(.home):
            return .choice(([country.homePhrase] + country.altHomePhrases).map { .text($0) })
        case .slot(.country): return .text(country.nameIt)
        case .slot(.nationality):
            if country.nationalityM == country.nationalityF { return .text(country.nationalityM) }
            return .gendered([
                .init(gender: .m, node: .text(country.nationalityM)),
                .init(gender: .f, node: .text(country.nationalityF)),
            ])
        case .slot: return self
        case .sequence(let nodes): return .sequence(nodes.map { $0.substituting(country) })
        case .choice(let nodes): return .choice(nodes.map { $0.substituting(country) })
        case .optional(let node): return .optional(node.substituting(country))
        case .focus(let node): return .focus(node.substituting(country))
        case .gendered(let options):
            return .gendered(options.map { .init(gender: $0.gender, node: $0.node.substituting(country)) })
        }
    }

    enum Piece: Hashable {
        case text(String, focus: Bool)
        case slot(PatternSlot, focus: Bool)
    }

    struct Partial {
        var pieces: [Piece]
        var gender: PatternExpansion.Gender?

        static let empty = Partial(pieces: [], gender: nil)

        func appending(_ other: Partial) -> Partial? {
            var gender = self.gender
            if let g = other.gender {
                if let mine = gender, mine != g { return nil }
                gender = g
            }
            return Partial(pieces: pieces + other.pieces, gender: gender)
        }

        func expansion() -> PatternExpansion {
            var tokens: [String] = []
            var focus: [Int] = []
            var slots: [PatternExpansion.SlotPosition] = []
            var segments = [""]
            var run: [(String, Bool)] = []
            func flush() {
                for token in Normalizer.taggedTokens(run) {
                    if token.tagged { focus.append(tokens.count) }
                    tokens.append(token.text)
                }
                run = []
            }
            for piece in pieces {
                switch piece {
                case .text(let s, let f):
                    run.append((s, f))
                    segments[segments.count - 1] += s
                case .slot(let slot, let f):
                    flush()
                    if f { focus.append(tokens.count) }
                    slots.append(.init(tokenIndex: tokens.count, slot: slot))
                    tokens.append(slot.placeholder)
                    segments.append("")
                }
            }
            flush()
            var raw = segments[0]
            for (n, position) in slots.enumerated() { raw += position.slot.placeholder + segments[n + 1] }
            return PatternExpansion(
                raw: AnswerPattern.collapseSpaces(raw), tokens: tokens, focus: focus, gender: gender, slots: slots,
                rawSegments: segments)
        }
    }

    func partials(focus: Bool) -> [Partial] {
        switch self {
        case .text(let s): return [Partial(pieces: [.text(s, focus: focus)], gender: nil)]
        case .slot(let slot): return [Partial(pieces: [.slot(slot, focus: focus)], gender: nil)]
        case .sequence(let nodes):
            var result = [Partial.empty]
            for node in nodes {
                let next = node.partials(focus: focus)
                result = result.flatMap { head in next.compactMap { head.appending($0) } }
            }
            return result
        case .choice(let nodes): return nodes.flatMap { $0.partials(focus: focus) }
        case .optional(let node): return node.partials(focus: focus) + [.empty]
        case .focus(let node): return node.partials(focus: true)
        case .gendered(let options):
            return options.flatMap { option in
                option.node.partials(focus: focus).compactMap {
                    Partial(pieces: [], gender: option.gender).appending($0)
                }
            }
        }
    }
}

/// Two normalised tokens taken as forms of the same word, in either order.
struct FormPair: Hashable, Sendable {
    let a: String
    let b: String

    init(_ x: String, _ y: String) {
        (a, b) = x < y ? (x, y) : (y, x)
    }
}

extension AnswerPattern {
    /// Collapses runs of whitespace and trims (for display strings built from pattern pieces).
    static func collapseSpaces(_ text: String) -> String {
        text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }
}
