import Foundation

/// Picks today's reviews: everything due, plus up to the daily limit of new items (HANDOFF.md 3.6).
public enum ReviewQueue {
    public struct Item<Key: Hashable & Sendable>: Sendable {
        public let key: Key
        public let schedule: Schedule?   // nil = never reviewed
        public let createdAt: Date

        public init(key: Key, schedule: Schedule?, createdAt: Date) {
            self.key = key
            self.schedule = schedule
            self.createdAt = createdAt
        }
    }

    /// Due reviews first (most overdue first), then new items oldest first.
    public static func build<Key>(_ items: [Item<Key>], now: Date, newLimit: Int, newSeenToday: Int) -> [Key] {
        let due = items.compactMap { item -> (Key, Date)? in
            guard let s = item.schedule, s.reps > 0, s.due <= now else { return nil }
            return (item.key, s.due)
        }.sorted { $0.1 < $1.1 }.map(\.0)
        let new = items.filter { $0.schedule == nil || $0.schedule?.reps == 0 }
            .sorted { $0.createdAt < $1.createdAt }
            .prefix(max(0, newLimit - newSeenToday))
            .map(\.key)
        return due + new
    }

    /// A short human label for an interval: "1 min", "10 min", "3 days", "2 mo".
    public static func label(from now: Date, to due: Date) -> String {
        let seconds = max(0, due.timeIntervalSince(now))
        let minutes = Int((seconds / 60).rounded())
        if minutes < 60 { return "\(max(1, minutes)) min" }
        let hours = Int((seconds / 3600).rounded())
        if hours < 24 { return "\(hours) h" }
        let days = Int((seconds / 86400).rounded())
        if days < 31 { return days == 1 ? "1 day" : "\(days) days" }
        if days < 365 { return "\(days / 30) mo" }
        let years = Double(days) / 365
        return String(format: "%.1f yr", years)
    }
}
