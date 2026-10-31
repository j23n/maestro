import Foundation

/// Pack ranges are [start, length] in UTF-16 code units over NFC text (HANDOFF.md 6.3).
public struct UTF16Range: Hashable, Sendable, Codable {
    public var start: Int
    public var length: Int

    public init(start: Int, length: Int) {
        self.start = start
        self.length = length
    }

    public var end: Int { start + length }

    public func contains(_ offset: Int) -> Bool { offset >= start && offset < end }

    public func overlaps(_ other: UTF16Range) -> Bool { start < other.end && other.start < end }

    public init(from decoder: Decoder) throws {
        var container = try decoder.unkeyedContainer()
        start = try container.decode(Int.self)
        length = try container.decode(Int.self)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.unkeyedContainer()
        try container.encode(start)
        try container.encode(length)
    }

    /// Ranges stored on a card: "14:6,27:3".
    public static func list(from string: String) -> [UTF16Range] {
        string.split(separator: ",").compactMap { part in
            let nums = part.split(separator: ":").compactMap { Int($0) }
            return nums.count == 2 ? UTF16Range(start: nums[0], length: nums[1]) : nil
        }
    }

    public static func string(from ranges: [UTF16Range]) -> String {
        ranges.map { "\($0.start):\($0.length)" }.joined(separator: ",")
    }
}

extension String {
    public var utf16Length: Int { utf16.count }

    /// The string range for a UTF-16 range, or nil if it falls outside or splits a character.
    public func range(of r: UTF16Range) -> Range<String.Index>? {
        let view = utf16
        guard r.start >= 0, r.length >= 0,
              let lower = view.index(view.startIndex, offsetBy: r.start, limitedBy: view.endIndex),
              let upper = view.index(lower, offsetBy: r.length, limitedBy: view.endIndex),
              let lo = String.Index(lower, within: self),
              let hi = String.Index(upper, within: self) else { return nil }
        return lo..<hi
    }

    public func substring(_ r: UTF16Range) -> String? {
        range(of: r).map { String(self[$0]) }
    }

    public func utf16Offset(of index: String.Index) -> Int {
        utf16.distance(from: utf16.startIndex, to: index)
    }
}
