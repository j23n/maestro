import Foundation

/// A content ID as a typed wrapper (docs/03 § IDs). The tag type keeps item, exercise and step IDs apart at
/// compile time; the raw value is exactly the ID string stored in the pack and in events.
public struct TypedID<Tag>: RawRepresentable, Hashable, Comparable, Codable, Sendable, CustomStringConvertible,
    ExpressibleByStringLiteral
{
    public let rawValue: String

    public init(rawValue: String) { self.rawValue = rawValue }
    public init(_ rawValue: String) { self.rawValue = rawValue }
    public init(stringLiteral value: String) { self.rawValue = value }

    public init(from decoder: Decoder) throws {
        rawValue = try decoder.singleValueContainer().decode(String.self)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        try c.encode(rawValue)
    }

    public static func < (lhs: Self, rhs: Self) -> Bool { lhs.rawValue < rhs.rawValue }
    public var description: String { rawValue }
}

public enum ItemTag {}
public enum ExerciseTag {}
public enum StepTag {}
public enum UnitTag {}
public enum LessonTag {}
public enum TextTag {}
public enum NoteTag {}
public enum CanDoTag {}
public enum AudioTag {}
public enum CharacterTag {}
public enum SyllabusTag {}

/// `w:` word, `c:` chunk, `g:` grammar point, `s:` sound.
public typealias ItemID = TypedID<ItemTag>
public typealias ExerciseID = TypedID<ExerciseTag>
public typealias StepID = TypedID<StepTag>
public typealias UnitID = TypedID<UnitTag>
public typealias LessonID = TypedID<LessonTag>
public typealias TextID = TypedID<TextTag>
public typealias NoteID = TypedID<NoteTag>
public typealias CanDoID = TypedID<CanDoTag>
public typealias AudioID = TypedID<AudioTag>
public typealias CharacterID = TypedID<CharacterTag>
public typealias SyllabusID = TypedID<SyllabusTag>

/// Item kinds, from the ID prefix (docs/03 § IDs).
public enum ItemKind: String, Codable, Sendable, CaseIterable {
    case word, chunk, grammar, sound

    public init?(itemID: ItemID) {
        switch itemID.rawValue.prefix(2) {
        case "w:": self = .word
        case "c:": self = .chunk
        case "g:": self = .grammar
        case "s:": self = .sound
        default: return nil
        }
    }
}

extension TypedID where Tag == ItemTag {
    public var kind: ItemKind? { ItemKind(itemID: self) }
}

extension TypedID where Tag == AudioTag {
    /// `a:3f9c0e1a2b4d` → `3f9c0e1a2b4d.m4a`; the app always reads `audio.file`, this is only a fallback.
    public var fileName: String { String(rawValue.dropFirst(2)) + ".m4a" }
}
