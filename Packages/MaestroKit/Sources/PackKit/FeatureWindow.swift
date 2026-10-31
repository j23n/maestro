import Foundation

/// When the library features a text: a span of days that comes back every year, such as
/// `12-01..01-06` (1 December to 6 January) or `easter-60..easter-47` (the weeks of Carnevale).
/// Each end is a month and day, or a number of days from Easter Sunday. A span whose end comes
/// before its start runs over the new year. Both ends are included.
public struct FeatureWindow: Sendable, Hashable, CustomStringConvertible {
    public enum Day: Sendable, Hashable {
        case fixed(month: Int, day: Int)
        case easter(offset: Int)
    }

    public let start: Day
    public let end: Day

    public init(start: Day, end: Day) {
        self.start = start
        self.end = end
    }

    public init?(_ text: String) {
        let parts = text.split(separator: ".", omittingEmptySubsequences: true)
        guard text.contains(".."), parts.count == 2,
              let start = Self.day(String(parts[0])), let end = Self.day(String(parts[1])) else { return nil }
        self.init(start: start, end: end)
    }

    private static func day(_ text: String) -> Day? {
        if text.hasPrefix("easter") {
            let rest = text.dropFirst("easter".count)
            guard let sign = rest.first, sign == "+" || sign == "-", let n = Int(rest.dropFirst()) else { return nil }
            return .easter(offset: sign == "-" ? -n : n)
        }
        let md = text.split(separator: "-")
        guard md.count == 2, let month = Int(md[0]), let day = Int(md[1]),
              (1...12).contains(month), (1...31).contains(day) else { return nil }
        return .fixed(month: month, day: day)
    }

    public var description: String { "\(Self.text(start))..\(Self.text(end))" }

    private static func text(_ day: Day) -> String {
        switch day {
        case .fixed(let m, let d): String(format: "%02d-%02d", m, d)
        case .easter(let n): n < 0 ? "easter\(n)" : "easter+\(n)"
        }
    }

    /// Whether the window holds the given date's day in the calendar's time zone.
    public func contains(_ date: Date, calendar: Calendar = Calendar(identifier: .gregorian)) -> Bool {
        let year = calendar.component(.year, from: date)
        guard let today = Self.ordinal(calendar.startOfDay(for: date), calendar),
              let first = resolve(start, year: year, calendar), let last = resolve(end, year: year, calendar)
        else { return false }
        if first <= last { return first <= today && today <= last }
        return today >= first || today <= last  // runs over the new year
    }

    /// Day of the year of one end of the window, in the given year.
    private func resolve(_ day: Day, year: Int, _ calendar: Calendar) -> Int? {
        let date: Date?
        switch day {
        case .fixed(let month, let d):
            date = calendar.date(from: DateComponents(year: year, month: month, day: d))
        case .easter(let offset):
            let e = Self.easter(year: year)
            date = calendar.date(from: DateComponents(year: year, month: e.month, day: e.day))
                .flatMap { calendar.date(byAdding: .day, value: offset, to: $0) }
        }
        return date.flatMap { Self.ordinal($0, calendar) }
    }

    private static func ordinal(_ date: Date, _ calendar: Calendar) -> Int? {
        calendar.ordinality(of: .day, in: .year, for: date)
    }

    /// Easter Sunday in the Gregorian calendar (the anonymous Gregorian algorithm).
    public static func easter(year: Int) -> (month: Int, day: Int) {
        let a = year % 19, b = year / 100, c = year % 100
        let d = b / 4, e = b % 4
        let f = (b + 8) / 25, g = (b - f + 1) / 3
        let h = (19 * a + b - d - g + 15) % 30
        let i = c / 4, k = c % 4
        let l = (32 + 2 * e + 2 * i - h - k) % 7
        let m = (a + 11 * h + 22 * l) / 451
        let month = (h + l - 7 * m + 114) / 31
        let day = (h + l - 7 * m + 114) % 31 + 1
        return (month, day)
    }
}
