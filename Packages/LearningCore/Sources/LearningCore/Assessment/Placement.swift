import Foundation

/// What placement writes: `placementCompleted` and, unless the learner starts from the beginning, one
/// `introduced` event (via `placement`) for every item in the skipped units.
public struct PlacementCompletion: Hashable, Sendable {
    public var completed: PlacementCompletedPayload
    public var introduced: IntroducedPayload?

    public init(completed: PlacementCompletedPayload, introduced: IntroducedPayload?) {
        self.completed = completed
        self.introduced = introduced
    }

    public var startUnit: UnitID { completed.startUnit }
}

/// The placement algorithm (docs/05 § Placement): blocks for Units 1–8, five items each. Start with the first
/// block; a block scoring at least 4 advances to the next, otherwise placement stops. The start unit is the first
/// block that scored below 4, or the unit after the last block (Unit 9) if every block passes.
public enum Placement {
    /// Scores one block: full credit 1, `almost` half (check scoring), times each item's score.
    public static func blockResult(_ block: ContentIndex.PlacementAssessment.Block,
                                   answers: [ExerciseID: AttemptOutcome], content: ContentIndex) -> PlacementBlockResult
    {
        var correct = 0.0
        var total = 0.0
        for id in block.exerciseIds {
            let score = Double(content.exercise(id)?.score ?? 1)
            total += score
            correct += CheckScoring.earned(score: score, answer: answers[id].map { CheckAnswer.outcome($0) })
        }
        return PlacementBlockResult(unit: block.unitId, correct: correct, total: total)
    }

    public static func passes(_ result: PlacementBlockResult, assessment: ContentIndex.PlacementAssessment) -> Bool {
        result.correct + CheckScoring.epsilon >= assessment.advanceThreshold
    }

    /// The block to run next, or nil when placement is over (a block failed, or every block has been run).
    public static func nextBlock(after results: [PlacementBlockResult], assessment: ContentIndex.PlacementAssessment)
        -> ContentIndex.PlacementAssessment.Block?
    {
        if let last = results.last, !passes(last, assessment: assessment) { return nil }
        return results.count < assessment.blocks.count ? assessment.blocks[results.count] : nil
    }

    /// The start unit once placement is over, or nil while blocks remain.
    public static func startUnit(results: [PlacementBlockResult], assessment: ContentIndex.PlacementAssessment,
                                 content: ContentIndex) -> UnitID?
    {
        if let failed = results.first(where: { !passes($0, assessment: assessment) }) { return failed.unit }
        guard results.count >= assessment.blocks.count, let lastBlock = assessment.blocks.last else { return nil }
        return content.unit(after: lastBlock.unitId)?.id ?? lastBlock.unitId
    }

    /// "Start there": `placementCompleted` plus the introductions of every item in the units before the start
    /// unit. Nil while blocks remain.
    public static func completion(results: [PlacementBlockResult], assessment: ContentIndex.PlacementAssessment,
                                  content: ContentIndex) -> PlacementCompletion?
    {
        guard let start = startUnit(results: results, assessment: assessment, content: content) else { return nil }
        return PlacementCompletion(
            completed: PlacementCompletedPayload(startUnit: start, blocks: results),
            introduced: Introductions.placementPayload(startUnit: start, content: content))
    }

    /// "Start from the beginning" (offered at any point): the first unit (`u00`) and no introductions.
    public static func startFromBeginning(results: [PlacementBlockResult] = [], content: ContentIndex)
        -> PlacementCompletion?
    {
        guard let first = content.units.first else { return nil }
        return PlacementCompletion(completed: PlacementCompletedPayload(startUnit: first.id, blocks: results),
                                   introduced: nil)
    }
}
