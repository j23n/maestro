import Foundation
import SwiftData
import ItalianCore
import LexiconKit
import SRSKit
import SyncLogic

/// Something the learner can keep, with the snapshot its card shows (HANDOFF.md 3.4).
struct RememberItem: Hashable, Identifiable {
    var key: String
    var kind: ItemKind
    var lemmaID = ""
    var senseID = ""
    var formTag = ""
    var grammarID = ""
    var surface = ""
    var sourceTextID = ""
    var sourceSentenceID = ""
    var sentenceText = ""
    var sentenceTranslation = ""
    var highlightRanges: [UTF16Range] = []

    var id: String { key }

    static func word(lemmaID: String, senseID: String, surface: String) -> RememberItem {
        RememberItem(key: ItemKey.word(lemmaID: lemmaID, senseID: senseID), kind: .word, lemmaID: lemmaID,
                     senseID: senseID, surface: surface)
    }

    static func verbForm(lemmaID: String, formTag: String, surface: String) -> RememberItem {
        RememberItem(key: ItemKey.verbForm(lemmaID: lemmaID, formTag: formTag), kind: .verbForm, lemmaID: lemmaID,
                     formTag: formTag, surface: surface)
    }

    static func grammar(_ id: String, surface: String) -> RememberItem {
        RememberItem(key: ItemKey.grammar(id), kind: .grammar, grammarID: id, surface: surface)
    }

    /// Attaches the sentence the item came from.
    func inSentence(textID: String, sentenceID: String, text: String, translation: String,
                    ranges: [UTF16Range]) -> RememberItem {
        var copy = self
        copy.sourceTextID = textID
        copy.sourceSentenceID = sentenceID
        copy.sentenceText = text
        copy.sentenceTranslation = translation
        copy.highlightRanges = ranges
        return copy
    }
}

/// Reads and writes learner data: cards, review logs, the local schedule cache, progress and
/// lookups, and runs the merge pass after sync (HANDOFF.md 5.2).
@MainActor struct RememberStore {
    let context: ModelContext
    let prefs: Preferences
    var content: ContentDatabase?

    var scheduler: FSRSScheduler { FSRSScheduler(parameters: prefs.fsrs) }

    // MARK: Cards

    func cards(for key: String) -> [Card] {
        let descriptor = FetchDescriptor<Card>(predicate: #Predicate { $0.itemKey == key },
                                               sortBy: [SortDescriptor(\.createdAt)])
        return (try? context.fetch(descriptor)) ?? []
    }

    func isKept(_ key: String) -> Bool {
        cards(for: key).contains { $0.isActive }
    }

    /// Keep or stop keeping. Keeping an item that was deleted restores its card and its history.
    func toggle(_ item: RememberItem) {
        let existing = cards(for: item.key)
        if existing.contains(where: \.isActive) {
            for card in existing where card.isActive { card.deletedAt = .now }
        } else if let card = existing.first {
            card.restoredAt = .now
        } else {
            let card = Card(itemKey: item.key, kind: item.kind.rawValue)
            card.lemmaID = item.lemmaID
            card.senseID = item.senseID
            card.formTag = item.formTag
            card.grammarID = item.grammarID
            card.surface = item.surface
            card.sourceTextID = item.sourceTextID
            card.sourceSentenceID = item.sourceSentenceID
            card.sentenceText = item.sentenceText.precomposedStringWithCanonicalMapping
            card.sentenceTranslation = item.sentenceTranslation
            card.highlightRanges = UTF16Range.string(from: item.highlightRanges)
            context.insert(card)
        }
        try? context.save()
    }

    func delete(_ card: Card) {
        for c in cards(for: card.itemKey) where c.isActive { c.deletedAt = .now }
        try? context.save()
    }

    // MARK: Reviews and schedule

    func logs(for key: String) -> [ReviewLog] {
        let descriptor = FetchDescriptor<ReviewLog>(predicate: #Predicate { $0.itemKey == key })
        return (try? context.fetch(descriptor)) ?? []
    }

    func scheduleState(for key: String) -> ScheduleState? {
        let descriptor = FetchDescriptor<ScheduleState>(predicate: #Predicate { $0.itemKey == key })
        return try? context.fetch(descriptor).first
    }

    func schedule(for key: String) -> Schedule? {
        scheduleState(for: key).map(Self.schedule(from:))
    }

    func review(_ card: Card, rating: Rating, durationMs: Int, at date: Date = .now) {
        let log = ReviewLog(itemKey: card.itemKey, cardID: card.id, reviewedAt: date,
                            tzOffsetMinutes: TimeZone.current.secondsFromGMT(for: date) / 60,
                            rating: rating.rawValue, durationMs: durationMs, deviceID: prefs.deviceID)
        context.insert(log)
        rebuild(key: card.itemKey)
        try? context.save()
    }

    /// Replays an item's logs into its local schedule.
    func rebuild(key: String) {
        let events = logs(for: key).compactMap(Self.event(from:))
        let schedule = scheduler.replay(events)
        let state = scheduleState(for: key) ?? {
            let s = ScheduleState(itemKey: key)
            context.insert(s)
            return s
        }()
        Self.apply(schedule, to: state)
        state.parametersVersion = prefs.fsrs.version
        state.logCount = events.count
    }

    /// Rebuilds every schedule whose logs changed (after a sync) or whose parameters changed.
    func rebuildAll() {
        let allLogs = (try? context.fetch(FetchDescriptor<ReviewLog>())) ?? []
        var byKey: [String: [ReviewEvent]] = [:]
        for log in allLogs {
            if let e = Self.event(from: log) { byKey[log.itemKey, default: []].append(e) }
        }
        let states = (try? context.fetch(FetchDescriptor<ScheduleState>())) ?? []
        var stateByKey: [String: ScheduleState] = [:]
        for s in states {
            if stateByKey[s.itemKey] != nil { context.delete(s) } else { stateByKey[s.itemKey] = s }
        }
        let version = prefs.fsrs.version
        for (key, events) in byKey {
            let state = stateByKey[key]
            if let state, state.logCount == events.count, state.parametersVersion == version { continue }
            let target = state ?? {
                let s = ScheduleState(itemKey: key)
                context.insert(s)
                return s
            }()
            Self.apply(scheduler.replay(events), to: target)
            target.parametersVersion = version
            target.logCount = events.count
        }
        for (key, state) in stateByKey where byKey[key] == nil {
            context.delete(state)
        }
        try? context.save()
    }

    /// How many new items were first reviewed today.
    func newReviewedToday(now: Date = .now) -> Int {
        let allLogs = (try? context.fetch(FetchDescriptor<ReviewLog>())) ?? []
        var first: [String: Date] = [:]
        for log in allLogs where first[log.itemKey].map({ log.reviewedAt < $0 }) ?? true {
            first[log.itemKey] = log.reviewedAt
        }
        let tz = TimeZone.current.secondsFromGMT(for: now) / 60
        let today = scheduler.dayNumber(now, tzOffsetMinutes: tz)
        return first.values.filter { scheduler.dayNumber($0, tzOffsetMinutes: tz) == today }.count
    }

    /// Today's queue: due cards, then new ones up to the daily limit.
    func queue(now: Date = .now) -> [Card] {
        let all = ((try? context.fetch(FetchDescriptor<Card>(sortBy: [SortDescriptor(\.createdAt)]))) ?? []).filter(\.isActive)
        var seen = Set<String>()
        let unique = all.filter { seen.insert($0.itemKey).inserted }
        let items = unique.map { card in
            ReviewQueue.Item(key: card.itemKey, schedule: schedule(for: card.itemKey), createdAt: card.createdAt)
        }
        let keys = ReviewQueue.build(items, now: now, newLimit: prefs.newItemsPerDay, newSeenToday: newReviewedToday(now: now))
        let byKey = Dictionary(unique.map { ($0.itemKey, $0) }, uniquingKeysWith: { a, _ in a })
        return keys.compactMap { byKey[$0] }
    }

    static func event(from log: ReviewLog) -> ReviewEvent? {
        guard let rating = Rating(rawValue: log.rating) else { return nil }
        return ReviewEvent(id: log.id, reviewedAt: log.reviewedAt, tzOffsetMinutes: log.tzOffsetMinutes, rating: rating)
    }

    static func schedule(from state: ScheduleState) -> Schedule {
        var s = Schedule(due: state.due)
        s.state = LearningState(rawValue: state.state) ?? .new
        s.step = state.step
        s.stability = state.stability
        s.difficulty = state.difficulty
        s.reps = state.reps
        s.lapses = state.lapses
        s.scheduledDays = state.scheduledDays
        s.lastReviewedAt = state.lastReviewedAt
        s.lastTZOffsetMinutes = state.lastTZOffsetMinutes
        return s
    }

    static func apply(_ s: Schedule, to state: ScheduleState) {
        state.state = s.state.rawValue
        state.step = s.step
        state.stability = s.stability
        state.difficulty = s.difficulty
        state.reps = s.reps
        state.lapses = s.lapses
        state.scheduledDays = s.scheduledDays
        state.lastReviewedAt = s.lastReviewedAt
        state.lastTZOffsetMinutes = s.lastTZOffsetMinutes
        state.due = s.due
    }

    // MARK: Progress

    func progress(for textID: String) -> TextProgress? {
        let descriptor = FetchDescriptor<TextProgress>(predicate: #Predicate { $0.textID == textID },
                                                       sortBy: [SortDescriptor(\.updatedAt, order: .reverse)])
        return try? context.fetch(descriptor).first
    }

    func updateProgress(textID: String, position: Double) {
        let p = progress(for: textID) ?? {
            let p = TextProgress(textID: textID)
            context.insert(p)
            return p
        }()
        p.position = position
        p.maxFractionRead = max(p.maxFractionRead, position)
        if position >= 0.98 && p.finishedAt == nil { p.finishedAt = .now }
        p.updatedAt = .now
        try? context.save()
    }

    func recordAnswer(textID: String, questionID: String, choice: Int) {
        let p = progress(for: textID) ?? {
            let p = TextProgress(textID: textID)
            context.insert(p)
            return p
        }()
        var answers = MergeRules.decodeAnswers(p.answersJSON)
        answers[questionID] = MergeRules.Answer(choice: choice, at: .now)
        p.answersJSON = MergeRules.encodeAnswers(answers)
        p.updatedAt = .now
        try? context.save()
    }

    // MARK: Lookups

    func recordLookup(query: String, lemmaID: String) {
        context.insert(LookupEntry(query: query, lemmaID: lemmaID))
        try? context.save()
    }

    // MARK: Merge pass

    /// Dedupes after sync (HANDOFF.md 5.2). Never touches review logs.
    func mergePass() {
        let cards = (try? context.fetch(FetchDescriptor<Card>())) ?? []
        let snapshots = cards.map {
            MergeRules.CardSnapshot(id: $0.id, itemKey: $0.itemKey, createdAt: $0.createdAt,
                                    deletedAt: $0.deletedAt, restoredAt: $0.restoredAt)
        }
        let content = self.content
        let grammarIDs = Set(content?.grammarTopics().map(\.id) ?? [])
        let plan = MergeRules.planCards(snapshots) { id in
            guard let content else { return nil }
            if !id.contains(":") { return grammarIDs.contains(id) ? id : nil }
            return content.known(id)
        }
        for card in cards {
            if plan.delete.contains(card.id) {
                context.delete(card)
            } else if plan.reactivate.contains(card.id) {
                card.restoredAt = .now
            }
        }

        let progress = (try? context.fetch(FetchDescriptor<TextProgress>())) ?? []
        for (_, group) in Dictionary(grouping: progress, by: \.textID) where group.count > 1 {
            let snaps = group.map {
                MergeRules.ProgressSnapshot(id: $0.id, textID: $0.textID, position: $0.position,
                                            maxFractionRead: $0.maxFractionRead, finishedAt: $0.finishedAt,
                                            answers: MergeRules.decodeAnswers($0.answersJSON), updatedAt: $0.updatedAt,
                                            createdOrder: $0.createdAt)
            }
            guard let merged = MergeRules.mergeProgress(snaps),
                  let survivor = group.first(where: { $0.id == merged.survivor.id }) else { continue }
            survivor.position = merged.survivor.position
            survivor.maxFractionRead = merged.survivor.maxFractionRead
            survivor.finishedAt = merged.survivor.finishedAt
            survivor.answersJSON = MergeRules.encodeAnswers(merged.survivor.answers)
            survivor.updatedAt = merged.survivor.updatedAt
            for record in group where merged.delete.contains(record.id) { context.delete(record) }
        }

        let lookups = (try? context.fetch(FetchDescriptor<LookupEntry>())) ?? []
        let trim = Set(MergeRules.trimLookups(lookups.map { (id: $0.id, at: $0.lookedUpAt) }))
        for entry in lookups where trim.contains(entry.id) { context.delete(entry) }
        try? context.save()
    }
}
