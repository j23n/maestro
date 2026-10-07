import Foundation

/// A unit's can-dos and which have been reached.
public struct CanDoProgress: Hashable, Sendable {
    public var unitId: UnitID
    public var reached: [CanDoID]
    public var total: Int
}

/// The current ISO week (Monday to Sunday) against the weekly goal. There is no streak counter.
public struct WeekProgress: Hashable, Sendable {
    /// Day number of the week's Monday.
    public var weekStart: Int64
    /// Monday … Sunday: whether each day counts as active.
    public var days: [Bool]
    public var goal: Int

    public var activeDays: Int { days.filter { $0 }.count }
    public var goalMet: Bool { activeDays >= goal }
}

/// Progress metrics (docs/05 § Progress metrics).
public enum Progress {
    public static let knownMinimumReps = 2
    public static let knownMinimumRetrievability = 0.85

    static let fsrs = FSRS6()

    /// Words known: word and chunk items whose scheduled skill has `reps ≥ 2` and current retrievability ≥ 0.85.
    public static func knownWords(state: LearnerState, content: ContentIndex, now: Int64) -> [ItemID] {
        content.items.filter { item in
            guard item.kind == .word || item.kind == .chunk else { return false }
            let scheduled = item.scheduledSkills
            return !scheduled.isEmpty
                && scheduled.allSatisfy { skill in
                    guard let memory = state.memory[ItemSkillPair(item.id, skill)] else { return false }
                    return memory.reps >= knownMinimumReps
                        && fsrs.retrievability(memory, atMs: now) >= knownMinimumRetrievability
                }
        }.map(\.id)
    }

    public static func wordsKnown(state: LearnerState, content: ContentIndex, now: Int64) -> Int {
        knownWords(state: state, content: content, now: now).count
    }

    /// Skill bars (Words screen): 0 no memory; 1: R < 0.5; 2: < 0.7; 3: < 0.9; 4: ≥ 0.9.
    public static func skillBars(_ pair: ItemSkillPair, state: LearnerState, now: Int64) -> Int {
        guard let memory = state.memory[pair] else { return 0 }
        let r = fsrs.retrievability(memory, atMs: now)
        if r < 0.5 { return 1 }
        if r < 0.7 { return 2 }
        if r < 0.9 { return 3 }
        return 4
    }

    /// Bars for all four skills of an item.
    public static func skillBars(item: ItemID, state: LearnerState, now: Int64) -> [Skill: Int] {
        var bars: [Skill: Int] = [:]
        for skill in Skill.allCases { bars[skill] = skillBars(ItemSkillPair(item, skill), state: state, now: now) }
        return bars
    }

    /// Can-dos reached per unit (from checks).
    public static func canDos(in unitId: UnitID, state: LearnerState, content: ContentIndex) -> CanDoProgress {
        let all = content.canDos(in: unitId)
        return CanDoProgress(unitId: unitId, reached: all.map(\.id).filter { state.canDos[$0] != nil },
                             total: all.count)
    }

    /// Active days this ISO week (≥ 1 completed step or ≥ 5 reviewed cards) against the weekly goal.
    public static func week(state: LearnerState, now: Int64, tzOffsetMinutes: Int, goal: Int) -> WeekProgress {
        let today = LocalDay.dayNumber(ms: now, tzOffsetMinutes: tzOffsetMinutes)
        let monday = LocalDay.weekStart(dayNumber: today)
        let days = (0..<7).map { state.activity(day: monday + Int64($0)).isActive }
        return WeekProgress(weekStart: monday, days: days, goal: goal)
    }
}
