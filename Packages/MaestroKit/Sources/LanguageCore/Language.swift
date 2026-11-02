import Foundation

/// A language the app teaches (HANDOFF.md 5.3). One is active at a time; content, the Remember deck and
/// most preferences are kept per language.
public enum Language: String, Sendable, Codable, CaseIterable, Hashable, Identifiable {
    case it, de

    public var id: String { rawValue }

    /// The language's English name, for UI copy: "Italian".
    public var name: String {
        switch self {
        case .it: "Italian"
        case .de: "German"
        }
    }

    /// The language's name in itself: "Italiano".
    public var endonym: String {
        switch self {
        case .it: "Italiano"
        case .de: "Deutsch"
        }
    }

    /// BCP 47 tag for speech voices, VoiceOver and translation: "it-IT".
    public var bcp47: String {
        switch self {
        case .it: "it-IT"
        case .de: "de-DE"
        }
    }

    /// Locale identifier: "it_IT".
    public var localeIdentifier: String { bcp47.replacingOccurrences(of: "-", with: "_") }

    /// Letters a typed answer may need that a keyboard set to English lacks.
    public var accentKeys: [String] {
        switch self {
        case .it: ["à", "è", "é", "ì", "ò", "ù"]
        case .de: ["ä", "ö", "ü", "ß"]
        }
    }

    /// The prefix of the language's content IDs: "de:" (HANDOFF.md 6.5).
    public var idPrefix: String { "\(rawValue):" }

    /// The language a content ID belongs to. Lemma and sense IDs always carry their language
    /// (`it:andare:v`, `de:gehen:v#k3fq`), German grammar and text IDs do too (`de:dativ`), and an ID
    /// without a prefix is Italian (`future-in-the-past`, `inverno-01`). Nil for a prefix this build
    /// doesn't know (`fr:maison:n`, from a later build): such items stay hidden and untouched.
    public static func of(id: String) -> Language? {
        guard let colon = id.firstIndex(of: ":") else { return .it }
        return Language(rawValue: String(id[..<colon]))
    }

    /// The language of an item key (HANDOFF.md 6.5), read from the content ID it carries; nil when
    /// that ID's language is unknown to this build.
    public static func of(itemKey: String) -> Language? {
        let parts = itemKey.split(separator: "|", omittingEmptySubsequences: false)
        guard parts.count >= 2 else { return .it }
        return of(id: String(parts[1]))
    }
}
