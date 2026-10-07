import Foundation

/// How one check item was answered.
public enum CheckAnswer: Hashable, Sendable {
    /// Closed formats (and any item graded to one outcome): full for `correct`/`correctWithNote`, half for
    /// `almost`, nothing otherwise.
    case outcome(AttemptOutcome)
    /// Talk and writing: content points found against the points required to pass (`pass`).
    case points(found: Int, required: Int)
    /// Conversation: goals completed out of the conversation's goals.
    case goals(completed: Int, total: Int)
}

/// A scored unit check.
public struct CheckResult: Hashable, Sendable {
    public var checkId: CheckID
    public var sections: [CheckSectionResult]
    public var overall: Double
    public var passed: Bool
    public var canDosReached: [CanDoID]
    /// Primary targets of items that earned nothing: the focus items if the check failed (replay derives them
    /// again from the attempts).
    public var wrongTargets: [ItemSkillPair]

    /// Sections the device couldn't do, flagged on the result screen.
    public var excludedSections: [String] { sections.filter(\.excluded).map(\.id) }

    /// The `checkCompleted` payload.
    public var payload: CheckCompletedPayload {
        CheckCompletedPayload(checkId: checkId, kind: .unit, sections: sections, overall: overall, passed: passed,
                              canDosReached: canDosReached)
    }
}

/// A scored final A1 check: five sections of 12 points, indicative pass ≥ 7/12 in every section.
public struct FinalCheckResult: Hashable, Sendable {
    public struct Section: Hashable, Sendable {
        public var id: String
        /// Points out of `max` (earned / possible scaled to the section's 12 points).
        public var points: Double
        public var max: Double
        public var excluded: Bool
        public var passed: Bool
    }

    public var checkId: CheckID
    public var sections: [Section]
    /// Every section that the device could do reached the indicative pass mark. Indicative only (docs/06 §20).
    public var indicativePass: Bool
    public var canDosReached: [CanDoID]

    /// The `checkCompleted` payload (`kind: final`): sections in points out of 12.
    public var payload: CheckCompletedPayload {
        let counted = sections.filter { !$0.excluded }
        let possible = counted.reduce(0) { $0 + $1.max }
        let earned = counted.reduce(0) { $0 + $1.points }
        return CheckCompletedPayload(
            checkId: checkId, kind: .final,
            sections: sections.map {
                CheckSectionResult(id: $0.id, earned: $0.points, possible: $0.max, excluded: $0.excluded)
            },
            overall: possible > 0 ? earned / possible : 0, passed: indicativePass, canDosReached: canDosReached)
    }
}

/// Unit check and final check scoring (docs/05 § Unit check scoring, § Final A1 check).
public enum CheckScoring {
    /// Tolerance for comparing score fractions with pass marks.
    static let epsilon = 1e-9

    /// Points an item earns: `score` × credit for outcomes; `score × found/required` capped at `score` for talk and
    /// writing; `score × goals completed / goals` for conversations. Unanswered items earn nothing.
    public static func earned(score: Double, answer: CheckAnswer?) -> Double {
        guard let answer else { return 0 }
        switch answer {
        case .outcome(let outcome):
            return score * outcome.checkCredit
        case .points(let found, let required):
            guard required > 0 else { return score }
            return min(score, score * Double(max(0, found)) / Double(required))
        case .goals(let completed, let total):
            guard total > 0 else { return 0 }
            return min(score, score * Double(max(0, completed)) / Double(total))
        }
    }

    /// The item earned its full score (the can-do rule).
    public static func isFullScore(_ answer: CheckAnswer?) -> Bool {
        earned(score: 1, answer: answer) >= 1 - epsilon
    }

    /// ⌈2/3 × n⌉: how many of a can-do's n tagged check exercises must earn their full score.
    public static func requiredForCanDo(taggedCount n: Int) -> Int { (2 * n + 2) / 3 }

    /// Can-dos reached by these (counted) exercises.
    public static func canDosReached(exerciseIds: [ExerciseID], answers: [ExerciseID: CheckAnswer],
                                     content: ContentIndex) -> [CanDoID]
    {
        var tagged: [CanDoID: Int] = [:]
        var full: [CanDoID: Int] = [:]
        for id in exerciseIds {
            guard let exercise = content.exercise(id) else { continue }
            let isFull = isFullScore(answers[id])
            for canDo in Set(exercise.canDoTags) {
                tagged[canDo, default: 0] += 1
                if isFull { full[canDo, default: 0] += 1 }
            }
        }
        return tagged.keys.sorted().filter { (full[$0] ?? 0) >= requiredForCanDo(taggedCount: tagged[$0] ?? 0) }
    }

    /// Scores a unit check. Excluded sections (speaking with no speech recognition, or speaking switched off) are
    /// flagged and count neither for the overall score nor for the pass rule nor for can-dos.
    public static func score(check: ContentIndex.Check, answers: [ExerciseID: CheckAnswer],
                             excludedSections: Set<String> = [], content: ContentIndex) -> CheckResult
    {
        var sections: [CheckSectionResult] = []
        var counted: [ExerciseID] = []
        var wrongTargets = Set<ItemSkillPair>()
        for section in check.sections {
            let excluded = excludedSections.contains(section.id)
            var sectionEarned = 0.0
            var possible = 0.0
            for id in section.exerciseIds {
                let score = Double(content.exercise(id)?.score ?? 1)
                let points = earned(score: score, answer: answers[id])
                sectionEarned += points
                possible += score
                if !excluded {
                    counted.append(id)
                    if points <= 0 { wrongTargets.formUnion(content.exercise(id)?.targets ?? []) }
                }
            }
            sections.append(
                CheckSectionResult(id: section.id, earned: sectionEarned, possible: possible, excluded: excluded))
        }
        let scored = sections.filter { !$0.excluded }
        let possible = scored.reduce(0) { $0 + $1.possible }
        let overall = possible > 0 ? scored.reduce(0) { $0 + $1.earned } / possible : 0
        let passed =
            possible > 0 && overall + epsilon >= check.passOverall
            && scored.allSatisfy { $0.fraction + epsilon >= check.sectionMin }
        return CheckResult(checkId: check.id, sections: sections, overall: overall, passed: passed,
                           canDosReached: canDosReached(exerciseIds: counted, answers: answers, content: content),
                           wrongTargets: wrongTargets.sorted())
    }

    /// Scores the final A1 check: each section's points out of its maximum (12), indicative pass when every
    /// counted section reaches 7.
    public static func scoreFinal(_ final: ContentIndex.FinalAssessment, answers: [ExerciseID: CheckAnswer],
                                  excludedSections: Set<String> = [], content: ContentIndex) -> FinalCheckResult
    {
        var sections: [FinalCheckResult.Section] = []
        var counted: [ExerciseID] = []
        for section in final.sections {
            let excluded = excludedSections.contains(section.id)
            var sectionEarned = 0.0
            var possible = 0.0
            for id in section.exerciseIds {
                let score = Double(content.exercise(id)?.score ?? 1)
                sectionEarned += earned(score: score, answer: answers[id])
                possible += score
                if !excluded { counted.append(id) }
            }
            let max = section.max ?? 12
            let points = possible > 0 ? sectionEarned / possible * max : 0
            sections.append(FinalCheckResult.Section(
                id: section.id, points: points, max: max, excluded: excluded,
                passed: points + epsilon >= final.indicativePassPerSection))
        }
        let scored = sections.filter { !$0.excluded }
        return FinalCheckResult(
            checkId: final.id, sections: sections,
            indicativePass: !scored.isEmpty && scored.allSatisfy(\.passed),
            canDosReached: canDosReached(exerciseIds: counted, answers: answers, content: content))
    }
}
