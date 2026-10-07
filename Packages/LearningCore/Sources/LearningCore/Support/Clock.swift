import Foundation

/// The only source of "now" in LearningCore (CLAUDE.md hard rule 3). Tests use `FixedClock`.
public protocol Clock: Sendable {
    /// Milliseconds since the Unix epoch, UTC.
    func nowMs() -> Int64
    /// The device's UTC offset in minutes at that moment (local-day maths, docs/05).
    func tzOffsetMinutes() -> Int
}

/// A clock that always returns the same instant; advance it explicitly in tests and simulations.
public final class FixedClock: Clock, @unchecked Sendable {
    // @unchecked: mutable state guarded by `lock`; used from tests and single-threaded simulations.
    private let lock = NSLock()
    private var ms: Int64
    private var offset: Int

    public init(ms: Int64, tzOffsetMinutes: Int = 0) {
        self.ms = ms
        self.offset = tzOffsetMinutes
    }

    public func nowMs() -> Int64 { lock.withLock { ms } }
    public func tzOffsetMinutes() -> Int { lock.withLock { offset } }

    public func advance(byMs delta: Int64) { lock.withLock { ms += delta } }
    public func set(ms newValue: Int64) { lock.withLock { ms = newValue } }
    public func set(tzOffsetMinutes newValue: Int) { lock.withLock { offset = newValue } }
}

/// Local days start at 04:00 in the event's own UTC offset (docs/05 § Determinism helpers).
public enum LocalDay {
    public static let rolloverHour: Int64 = 4
    public static let msPerDay: Int64 = 86_400_000

    /// Days since 1970-01-01 of the local day that contains `ms` (with the 04:00 rollover).
    public static func dayNumber(ms: Int64, tzOffsetMinutes: Int) -> Int64 {
        let local = ms + Int64(tzOffsetMinutes) * 60_000 - rolloverHour * 3_600_000
        return floorDiv(local, msPerDay)
    }

    /// `YYYY-MM-DD` of the local day (proleptic Gregorian, computed without Calendar so it is identical everywhere).
    public static func string(ms: Int64, tzOffsetMinutes: Int) -> String {
        string(dayNumber: dayNumber(ms: ms, tzOffsetMinutes: tzOffsetMinutes))
    }

    public static func string(dayNumber: Int64) -> String {
        let (y, m, d) = civil(fromDays: dayNumber)
        return String(format: "%04d-%02d-%02d", y, m, d)
    }

    /// UTC milliseconds at which the local day `dayNumber` ends (the next 04:00 local).
    public static func endMs(dayNumber: Int64, tzOffsetMinutes: Int) -> Int64 {
        (dayNumber + 1) * msPerDay + rolloverHour * 3_600_000 - Int64(tzOffsetMinutes) * 60_000
    }

    /// UTC milliseconds at which the local day `dayNumber` starts (04:00 local).
    public static func startMs(dayNumber: Int64, tzOffsetMinutes: Int) -> Int64 {
        endMs(dayNumber: dayNumber - 1, tzOffsetMinutes: tzOffsetMinutes)
    }

    /// ISO weekday of a day number: 1 = Monday … 7 = Sunday (1970-01-01 was a Thursday).
    public static func isoWeekday(dayNumber: Int64) -> Int {
        Int(floorMod(dayNumber + 3, 7)) + 1
    }

    /// Day number of the Monday that starts the ISO week containing `dayNumber`.
    public static func weekStart(dayNumber: Int64) -> Int64 {
        dayNumber - Int64(isoWeekday(dayNumber: dayNumber) - 1)
    }

    static func floorDiv(_ a: Int64, _ b: Int64) -> Int64 {
        let q = a / b
        return (a % b != 0 && (a < 0) != (b < 0)) ? q - 1 : q
    }

    static func floorMod(_ a: Int64, _ b: Int64) -> Int64 {
        a - floorDiv(a, b) * b
    }

    /// Howard Hinnant's days-to-civil algorithm.
    static func civil(fromDays z0: Int64) -> (Int64, Int64, Int64) {
        let z = z0 + 719_468
        let era = floorDiv(z, 146_097)
        let doe = z - era * 146_097
        let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365
        let y = yoe + era * 400
        let doy = doe - (365 * yoe + yoe / 4 - yoe / 100)
        let mp = (5 * doy + 2) / 153
        let d = doy - (153 * mp + 2) / 5 + 1
        let m = mp < 10 ? mp + 3 : mp - 9
        return (m <= 2 ? y + 1 : y, m, d)
    }
}
