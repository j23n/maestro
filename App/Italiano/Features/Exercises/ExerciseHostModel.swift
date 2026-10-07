import Foundation
import LearningCore

/// One exercise's view model, chosen by its payload (docs/06 § Payloads). The player makes a fresh one per exercise
/// page, so retrying an exercise after leaving it starts clean.
@MainActor
enum ExerciseHostModel {
    case typed(TypedExerciseModel)
    case choice(ChoiceModel)
    case match(MatchModel)
    case building(SentenceBuildingModel)
    case dictation(DictationModel)
    case repeatAfterMe(RepeatModel)
    case conversation(ConversationModel)
    case talk(TalkModel)
    case writing(WritingModel)
    case relay(RelayModel)

    /// Nil when the payload can't be played (a malformed pattern, a sound pair without its pair): the player skips
    /// the page and logs it, rather than showing a broken exercise.
    static func make(_ p: ExercisePayload, env: ExerciseEnvironment, sink: AttemptSink?) -> ExerciseHostModel? {
        switch p.body {
        case .cloze, .recall:
            TypedTask(payload: p).map { .typed(TypedExerciseModel(task: $0, env: env, sink: sink)) }
        case .choice, .trueFalse, .soundPair:
            ChoiceModel(payload: p, env: env, sink: sink).map { .choice($0) }
        case .match:
            MatchModel(payload: p, env: env, sink: sink).map { .match($0) }
        case .sentenceBuilding:
            SentenceBuildingModel(payload: p, env: env, sink: sink).map { .building($0) }
        case .dictation:
            DictationModel(payload: p, env: env, sink: sink).map { .dictation($0) }
        case .repeat:
            RepeatModel(payload: p, env: env, sink: sink).map { .repeatAfterMe($0) }
        case .conversation:
            ConversationModel(payload: p, env: env, sink: sink).map { .conversation($0) }
        case .talk:
            TalkModel(payload: p, env: env, sink: sink).map { .talk($0) }
        case .writing:
            WritingModel(payload: p, env: env, sink: sink).map { .writing($0) }
        case .relay:
            RelayModel(payload: p, env: env, sink: sink).map { .relay($0) }
        }
    }

    /// The exercise reached its end state (answered, revealed, skipped or finished).
    var isDone: Bool {
        switch self {
        case .typed(let m): m.isDone
        case .choice(let m): m.isDone
        case .match(let m): m.isDone
        case .building(let m): m.isDone
        case .dictation(let m): m.isDone
        case .repeatAfterMe(let m): m.isDone
        case .conversation(let m): m.isFinished
        case .talk(let m): m.result != nil
        case .writing(let m): m.submitted
        case .relay(let m): m.isDone
        }
    }
}
