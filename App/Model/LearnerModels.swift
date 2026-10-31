import Foundation
import SwiftData

// Learner data (HANDOFF.md 5.1). CloudKit rules: no unique attributes, every property optional or
// defaulted, never rename, delete or retype a property once the schema is in Production.

/// A kept item. Synced.
@Model final class Card {
    var id: UUID = UUID()
    var itemKey: String = ""
    var kind: String = "word"
    var lemmaID: String = ""
    var senseID: String = ""
    var formTag: String = ""
    var grammarID: String = ""
    var surface: String = ""
    var sourceTextID: String = ""
    var sourceSentenceID: String = ""
    var sentenceText: String = ""
    var sentenceTranslation: String = ""
    var highlightRanges: String = ""
    var createdAt: Date = Date.now
    var deletedAt: Date? = nil
    var restoredAt: Date? = nil

    init(itemKey: String, kind: String) {
        self.itemKey = itemKey
        self.kind = kind
    }

    var isActive: Bool {
        guard let deletedAt else { return true }
        guard let restoredAt else { return false }
        return restoredAt > deletedAt
    }
}

/// One review. Synced, append-only, the source of truth for the schedule.
@Model final class ReviewLog {
    var id: UUID = UUID()
    var itemKey: String = ""
    var cardID: UUID = UUID()
    var reviewedAt: Date = Date.now
    var tzOffsetMinutes: Int = 0
    var rating: Int = 0
    var durationMs: Int = 0
    var deviceID: String = ""

    init(itemKey: String, cardID: UUID, reviewedAt: Date, tzOffsetMinutes: Int, rating: Int, durationMs: Int,
         deviceID: String) {
        self.itemKey = itemKey
        self.cardID = cardID
        self.reviewedAt = reviewedAt
        self.tzOffsetMinutes = tzOffsetMinutes
        self.rating = rating
        self.durationMs = durationMs
        self.deviceID = deviceID
    }
}

/// Reading progress per text. Synced.
@Model final class TextProgress {
    var id: UUID = UUID()
    var textID: String = ""
    var position: Double = 0
    var maxFractionRead: Double = 0
    var finishedAt: Date? = nil
    var answersJSON: String = ""
    var updatedAt: Date = Date.now
    var createdAt: Date = Date.now      // the merge pass keeps the oldest record

    init(textID: String) {
        self.textID = textID
    }
}

/// Dictionary history. Synced, capped at 200.
@Model final class LookupEntry {
    var id: UUID = UUID()
    var query: String = ""
    var lemmaID: String = ""
    var lookedUpAt: Date = Date.now

    init(query: String, lemmaID: String) {
        self.query = query
        self.lemmaID = lemmaID
    }
}

/// The FSRS schedule of one item, rebuilt from review logs. Local only (cloudKitDatabase: .none).
@Model final class ScheduleState {
    var itemKey: String = ""
    var state: Int = 0
    var step: Int = 0
    var stability: Double = 0
    var difficulty: Double = 0
    var reps: Int = 0
    var lapses: Int = 0
    var scheduledDays: Int = 0
    var lastReviewedAt: Date? = nil
    var lastTZOffsetMinutes: Int = 0
    var due: Date = Date.now
    var parametersVersion: Int = 0
    var logCount: Int = 0

    init(itemKey: String) {
        self.itemKey = itemKey
    }
}

enum LearnerSchema {
    static var synced: [any PersistentModel.Type] { [Card.self, ReviewLog.self, TextProgress.self, LookupEntry.self] }
    static var local: [any PersistentModel.Type] { [ScheduleState.self] }

    /// Two stores: the synced one in the CloudKit private database (when the app is signed with the
    /// iCloud entitlement; otherwise local), and the schedule cache, never synced.
    @MainActor static func makeContainer(inMemory: Bool = false) -> ModelContainer {
        let all = Schema(synced + local)
        let syncedStore = ModelConfiguration("Learner", schema: Schema(synced), isStoredInMemoryOnly: inMemory,
                                             cloudKitDatabase: inMemory ? .none : .automatic)
        let localStore = ModelConfiguration("Schedule", schema: Schema(local), isStoredInMemoryOnly: inMemory,
                                            cloudKitDatabase: .none)
        do {
            return try ModelContainer(for: all, configurations: syncedStore, localStore)
        } catch {
            // CloudKit can refuse the store (no iCloud account in a test environment, say): fall back to
            // local storage rather than not launching.
            let fallback = ModelConfiguration("Learner", schema: Schema(synced), isStoredInMemoryOnly: inMemory,
                                              cloudKitDatabase: .none)
            do {
                return try ModelContainer(for: all, configurations: fallback, localStore)
            } catch {
                // Last resort: an in-memory store, so the app still opens and reads.
                do {
                    return try ModelContainer(for: all, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
                } catch {
                    fatalError("Can't create even an in-memory store: \(error)")
                }
            }
        }
    }
}
