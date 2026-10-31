import Foundation
import ItalianCore

/// The merge pass after each sync (HANDOFF.md 5.2), as pure functions over snapshots of the
/// SwiftData records so it can be tested without CloudKit. The app applies the returned plan.
public enum MergeRules {

    public struct CardSnapshot: Sendable, Hashable {
        public let id: UUID
        public let itemKey: String
        public let createdAt: Date
        public let deletedAt: Date?
        public let restoredAt: Date?

        public init(id: UUID, itemKey: String, createdAt: Date, deletedAt: Date? = nil, restoredAt: Date? = nil) {
            self.id = id
            self.itemKey = itemKey
            self.createdAt = createdAt
            self.deletedAt = deletedAt
            self.restoredAt = restoredAt
        }

        public var isActive: Bool { CardActivity.isActive(deletedAt: deletedAt, restoredAt: restoredAt) }
    }

    public struct CardPlan: Sendable, Equatable {
        /// Cards to delete (duplicates that lost).
        public var delete: Set<UUID> = []
        /// Survivors that must become active because a deleted duplicate was active.
        public var reactivate: Set<UUID> = []
    }

    /// Dedupe cards by item key after resolving IDs through `id_redirect`.
    /// - Parameter resolve: maps a stored ID to its current ID, or nil when the local content DB
    ///   doesn't know it. Cards with any unknown ID are never merged or deleted.
    public static func planCards(_ cards: [CardSnapshot], resolve: (String) -> String?) -> CardPlan {
        var plan = CardPlan()
        var groups: [String: [CardSnapshot]] = [:]
        for card in cards {
            guard let resolved = ItemKey.resolved(card.itemKey, resolve: resolve) else { continue }
            groups[resolved, default: []].append(card)
        }
        for group in groups.values {
            let sorted = group.sorted {
                $0.createdAt != $1.createdAt ? $0.createdAt < $1.createdAt : $0.id.uuidString < $1.id.uuidString
            }
            guard let survivor = sorted.first else { continue }
            let losers = sorted.dropFirst()
            plan.delete.formUnion(losers.map(\.id))
            if !survivor.isActive && losers.contains(where: \.isActive) {
                plan.reactivate.insert(survivor.id)
            }
        }
        return plan
    }

    // MARK: Text progress

    public struct Answer: Codable, Sendable, Hashable {
        public var choice: Int
        public var at: Date

        public init(choice: Int, at: Date) {
            self.choice = choice
            self.at = at
        }
    }

    public struct ProgressSnapshot: Sendable, Hashable {
        public var id: UUID
        public var textID: String
        public var position: Double
        public var maxFractionRead: Double
        public var finishedAt: Date?
        public var answers: [String: Answer]
        public var updatedAt: Date
        public var createdOrder: Date   // the record's age; oldest survives

        public init(id: UUID, textID: String, position: Double, maxFractionRead: Double, finishedAt: Date?,
                    answers: [String: Answer], updatedAt: Date, createdOrder: Date) {
            self.id = id
            self.textID = textID
            self.position = position
            self.maxFractionRead = maxFractionRead
            self.finishedAt = finishedAt
            self.answers = answers
            self.updatedAt = updatedAt
            self.createdOrder = createdOrder
        }
    }

    /// Merge duplicate progress records for one text into the oldest.
    public static func mergeProgress(_ records: [ProgressSnapshot]) -> (survivor: ProgressSnapshot, delete: [UUID])? {
        let sorted = records.sorted {
            $0.createdOrder != $1.createdOrder ? $0.createdOrder < $1.createdOrder : $0.id.uuidString < $1.id.uuidString
        }
        guard var survivor = sorted.first else { return nil }
        guard sorted.count > 1 else { return (survivor, []) }
        let newest = records.max { $0.updatedAt < $1.updatedAt }!
        survivor.position = newest.position
        survivor.updatedAt = newest.updatedAt
        survivor.maxFractionRead = records.map(\.maxFractionRead).max() ?? 0
        survivor.finishedAt = records.compactMap(\.finishedAt).min()
        var answers: [String: Answer] = [:]
        for record in records {
            for (q, a) in record.answers where answers[q].map({ a.at > $0.at }) ?? true {
                answers[q] = a
            }
        }
        survivor.answers = answers
        return (survivor, sorted.dropFirst().map(\.id))
    }

    public static func decodeAnswers(_ json: String) -> [String: Answer] {
        guard let data = json.data(using: .utf8), !data.isEmpty else { return [:] }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return (try? decoder.decode([String: Answer].self, from: data)) ?? [:]
    }

    public static func encodeAnswers(_ answers: [String: Answer]) -> String {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        return (try? encoder.encode(answers)).flatMap { String(data: $0, encoding: .utf8) } ?? ""
    }

    // MARK: Lookup history

    public static let lookupCap = 200

    /// IDs of lookup entries to trim, oldest first, so at most `cap` remain.
    public static func trimLookups(_ entries: [(id: UUID, at: Date)], cap: Int = lookupCap) -> [UUID] {
        guard entries.count > cap else { return [] }
        return entries.sorted { $0.at < $1.at }.prefix(entries.count - cap).map(\.id)
    }
}

public enum CardActivity {
    /// Active when deletedAt is nil or restoredAt is later than deletedAt.
    public static func isActive(deletedAt: Date?, restoredAt: Date?) -> Bool {
        guard let deleted = deletedAt else { return true }
        guard let restored = restoredAt else { return false }
        return restored > deleted
    }
}
