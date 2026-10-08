import Foundation
import LearningCore

// "Your words" (`Words.png`, docs/05 § Progress metrics, docs/07): every word and phrase the learner has met, with
// four skill bars, the next review and the filters All / Due today / Learning / New. Platform-neutral and tested.

struct WordRow: Sendable, Equatable, Identifiable {
    let id: ItemID
    let display: String
    let gloss: String
    /// read, listen, recall, speak: 0–4 bars, or nil for a skill the item doesn't schedule.
    let bars: [Int?]
    /// "Today", "Tomorrow", "In 3 days", "In 2 weeks", or nil before the first review.
    let nextReview: String?
    let isDueToday: Bool
    let status: Status
    /// Course order, for the default sort.
    let order: Int

    enum Status: Sendable, Equatable { case new, learning, known }
}

enum WordFilter: String, CaseIterable, Sendable {
    case all, dueToday, learning, new

    var title: String {
        switch self {
        case .all: "All"
        case .dueToday: "Due today"
        case .learning: "Learning"
        case .new: "New"
        }
    }

    func matches(_ row: WordRow) -> Bool {
        switch self {
        case .all: true
        case .dueToday: row.isDueToday
        case .learning: row.status == .learning
        case .new: row.status == .new
        }
    }
}

/// The learner's side of an item, independent of Storage: what the Words screen needs from the pack.
struct WordSource: Sendable, Equatable {
    let info: WordInfo
    let kind: ItemKind
    let scheduledSkills: [Skill]
    let order: Int
}

enum WordsCopy {
    static let skills: [Skill] = [.read, .listen, .recall, .speak]

    /// Words and phrases (not grammar points or sounds) with at least one introduced skill.
    static func rows(sources: [WordSource], state: LearnerState, nowMs: Int64, tzOffsetMinutes: Int) -> [WordRow] {
        let today = LocalDay.dayNumber(ms: nowMs, tzOffsetMinutes: tzOffsetMinutes)
        let endOfToday = LocalDay.endMs(dayNumber: today, tzOffsetMinutes: tzOffsetMinutes)
        return sources.compactMap { s -> WordRow? in
            guard s.kind == .word || s.kind == .chunk else { return nil }
            let pairs = s.scheduledSkills.map { ItemSkillPair(s.info.itemID, $0) }
            guard pairs.contains(where: state.isIntroduced) else { return nil }
            let memories = pairs.compactMap { state.memory[$0] }
            let due = memories.map(\.dueMs).min()
            let known =
                !memories.isEmpty && memories.count == pairs.count
                && memories.allSatisfy { $0.reps >= Progress.knownMinimumReps }
                && pairs.allSatisfy { Progress.skillBars($0, state: state, now: nowMs) >= 3 }
            return WordRow(
                id: s.info.itemID, display: s.info.display, gloss: s.info.gloss,
                bars: skills.map { skill in
                    s.scheduledSkills.contains(skill)
                        ? Progress.skillBars(ItemSkillPair(s.info.itemID, skill), state: state, now: nowMs) : nil
                },
                nextReview: due.map { nextReviewText(dueMs: $0, today: today, tzOffsetMinutes: tzOffsetMinutes) },
                isDueToday: due.map { $0 <= endOfToday } ?? false,
                status: memories.isEmpty ? .new : (known ? .known : .learning), order: s.order)
        }
        .sorted { ($0.order, $0.id) < ($1.order, $1.id) }
    }

    static func nextReviewText(dueMs: Int64, today: Int64, tzOffsetMinutes: Int) -> String {
        let days = LocalDay.dayNumber(ms: dueMs, tzOffsetMinutes: tzOffsetMinutes) - today
        switch days {
        case ...0: return "Today"
        case 1: return "Tomorrow"
        case 2..<14: return "In \(days) days"
        case 14..<60: return "In \(days / 7) weeks"
        default: return "In \(days / 30) months"
        }
    }

    static func counts(_ rows: [WordRow]) -> [WordFilter: Int] {
        Dictionary(uniqueKeysWithValues: WordFilter.allCases.map { f in (f, rows.filter(f.matches).count) })
    }

    /// "64 words · how well you know each one, skill by skill"
    static func subtitle(count: Int) -> String {
        "\(count) \(count == 1 ? "word" : "words") · how well you know each one, skill by skill"
    }
}
