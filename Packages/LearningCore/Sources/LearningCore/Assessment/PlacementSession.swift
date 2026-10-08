import Foundation

/// One sitting of placement (docs/05 § Placement, docs/06 §19): the adaptive blocks in order, one attempt per item,
/// no feedback. The app shows `currentExercise`, reports its single attempt with `record`, and calls `advance` when
/// the learner moves on; a finished block is scored like a check and decides whether the next block runs.
///
/// Only the blocks this pack can run take part: the assessment's blocks up to the first one that has no exercises
/// (or names one the pack lacks). A partial pack can't place anyone beyond a unit it has no questions for, so a
/// learner who passes every runnable block starts at the first unit without questions.
public struct PlacementSession: Equatable, Sendable {
    /// The runnable blocks, with the assessment's advance threshold.
    public let assessment: ContentIndex.PlacementAssessment
    /// Scored blocks, in order.
    public private(set) var results: [PlacementBlockResult] = []
    /// The index of the current exercise in the current block.
    public private(set) var position = 0
    /// The single attempt's outcome per exercise (later attempts are ignored).
    public private(set) var answers: [ExerciseID: AttemptOutcome] = [:]

    /// Nil when the pack has no runnable block (no placement row, or its first block has no exercises yet).
    public init?(assessment: ContentIndex.PlacementAssessment?, content: ContentIndex) {
        guard let assessment else { return nil }
        let blocks = Self.runnableBlocks(assessment, content: content)
        guard !blocks.isEmpty else { return nil }
        self.assessment = ContentIndex.PlacementAssessment(
            advanceThreshold: assessment.advanceThreshold, blocks: blocks)
    }

    /// The blocks up to the first one without exercises, or with an exercise or unit the pack lacks.
    public static func runnableBlocks(
        _ assessment: ContentIndex.PlacementAssessment, content: ContentIndex
    )
        -> [ContentIndex.PlacementAssessment.Block]
    {
        var blocks: [ContentIndex.PlacementAssessment.Block] = []
        for block in assessment.blocks {
            guard !block.exerciseIds.isEmpty, content.unit(block.unitId) != nil,
                block.exerciseIds.allSatisfy({ content.exercise($0) != nil })
            else { break }
            blocks.append(block)
        }
        return blocks
    }

    /// The block being run, or nil once placement is over.
    public var currentBlock: ContentIndex.PlacementAssessment.Block? {
        Placement.nextBlock(after: results, assessment: assessment)
    }

    /// The exercise on screen, or nil once placement is over.
    public var currentExercise: ExerciseID? {
        guard let block = currentBlock, position < block.exerciseIds.count else { return nil }
        return block.exerciseIds[position]
    }

    public var isFinished: Bool { currentBlock == nil }

    /// Exercises behind the learner (answered or passed over).
    public var answeredCount: Int {
        assessment.blocks.prefix(results.count).reduce(0) { $0 + $1.exerciseIds.count } + (isFinished ? 0 : position)
    }

    /// The most exercises this placement can ask (every runnable block): the progress bar's whole.
    public var maximumCount: Int { assessment.blocks.reduce(0) { $0 + $1.exerciseIds.count } }

    /// 0…1 for the progress bar; 1 once placement is over (it can stop early).
    public var progress: Double {
        isFinished || maximumCount == 0 ? 1 : Double(answeredCount) / Double(maximumCount)
    }

    /// The learner's one attempt at the current exercise. Anything else (a second attempt, another exercise) is
    /// ignored: placement has one attempt per item.
    public mutating func record(_ outcome: AttemptOutcome, for exercise: ExerciseID) {
        guard exercise == currentExercise, answers[exercise] == nil else { return }
        answers[exercise] = outcome
    }

    /// Moves past the current exercise (unanswered earns nothing). At the end of a block, scores it; a block below
    /// the threshold ends placement.
    public mutating func advance(content: ContentIndex) {
        guard let block = currentBlock else { return }
        position += 1
        if position >= block.exerciseIds.count {
            results.append(Placement.blockResult(block, answers: answers, content: content))
            position = 0
        }
    }

    /// The start unit once placement is over, or nil while blocks remain.
    public func startUnit(content: ContentIndex) -> UnitID? {
        Placement.startUnit(results: results, assessment: assessment, content: content)
    }

    /// "Start there": `placementCompleted` and the introductions of the skipped units. Nil while blocks remain.
    public func completion(content: ContentIndex) -> PlacementCompletion? {
        Placement.completion(results: results, assessment: assessment, content: content)
    }

    /// "Start from the beginning", at any point: the first unit, the blocks scored so far, no introductions.
    public func startFromBeginning(content: ContentIndex) -> PlacementCompletion? {
        Placement.startFromBeginning(results: results, content: content)
    }
}
