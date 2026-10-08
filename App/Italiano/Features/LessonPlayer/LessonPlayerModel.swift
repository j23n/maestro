import Foundation
import LearningCore
import Observation

// The lesson player's state (docs/06 § Shared player behaviour): a lesson's steps flattened into pages, the resume
// cursor derived from which exercises already have a final attempt (docs/05 § Replay), and the `n / total` progress
// over exercises. Platform-neutral and tested on Linux; LessonPlayerView draws it.

/// One line of a text as the player shows it (story, listening, reading, fluency).
struct PlayerLine: Sendable, Equatable {
    /// 1-based, as in `u02.l1.story#3`.
    let number: Int
    let speaker: CharacterID?
    let text: TokenizedText
    let english: String?
}

/// A text from the pack (`texts`, `text_lines`, `tokens`), ready to draw.
struct PlayerText: Sendable, Equatable {
    let id: TextID
    let title: String?
    let lines: [PlayerLine]
    let audioID: AudioID?
    /// Real-world texts are drawn natively from their layout (docs/06 §4).
    let layout: LayoutPayload?
}

/// Everything a lesson (or a unit's check) needs, loaded from the pack before the player opens, so the player never
/// waits on the database between pages.
struct LessonBundle: Sendable {
    struct Step: Sendable, Equatable {
        let id: StepID
        /// "Unit 2 · Grammar"
        let title: String
        let payload: StepPayload
    }

    let lessonID: LessonID
    let unitID: UnitID
    let title: String
    let steps: [Step]
    let exercises: [ExerciseID: ExercisePayload]
    var notes: [NoteID: NoteBody] = [:]
    var texts: [TextID: PlayerText] = [:]
    /// Display forms, glosses and notes: preview meet cards and the word panel.
    var items: [ItemID: WordInfo] = [:]
    /// Speaker labels in stories and dialogues (the story bible's display names).
    var characters: [CharacterID: String] = [:]
}

/// What the app shows for an item: a preview meet card, the mini-preview, the story's word panel.
struct WordInfo: Sendable, Equatable {
    let itemID: ItemID
    /// The display form (nouns with their article, docs/03).
    let display: String
    /// "noun", "verb", "chunk"…
    let partOfSpeech: String
    let gloss: String
    var note: String?
    var audioID: AudioID?
}

/// What fills the screen between the chrome.
enum PlayerPage: Sendable, Equatable {
    case opener(UnitID)
    case meet([ItemID])
    case story(TextID)
    case listening(TextID, plays: Int?)
    /// After a listening step's questions: "Show transcript" with read-along and glosses (docs/06 §3).
    case transcript(TextID)
    case reading(TextID)
    case note(NoteID)
    case fluency([TextID], rate: Double)
    case checkSection(id: String, title: String)
    case exercise(ExerciseID)
}

@MainActor
@Observable
final class LessonPlayerModel {
    struct Entry: Sendable, Equatable {
        let stepIndex: Int
        let page: PlayerPage
    }

    let bundle: LessonBundle
    let entries: [Entry]
    private(set) var position: Int
    private(set) var isFinished: Bool

    /// `answered`: exercises with a final attempt in this lesson (the engine's replay). `startingAt`: the step the
    /// learner picked (Unit overview); a step wholly before the resume point (already done) opens as a revisit at
    /// its first page; the step being worked on, or a later one, resumes as usual.
    init(bundle: LessonBundle, answered: Set<ExerciseID> = [], startingAt step: StepID? = nil) {
        self.bundle = bundle
        entries = Self.flatten(bundle)
        var start = Self.resumePosition(entries: entries, answered: answered)
        // A step that lies wholly before the resume point (finished) opens as a revisit at its first page.
        if let step, let i = bundle.steps.firstIndex(where: { $0.id == step }),
            let first = entries.firstIndex(where: { $0.stepIndex == i }),
            let last = entries.lastIndex(where: { $0.stepIndex == i }), last < start
        {
            start = first
        }
        position = start
        isFinished = start >= entries.count
    }

    var current: Entry? { isFinished ? nil : entries[safe: position] }
    var currentStep: LessonBundle.Step? { current.map { bundle.steps[$0.stepIndex] } }

    var currentExercise: ExercisePayload? {
        guard case .exercise(let id)? = current?.page else { return nil }
        return bundle.exercises[id]
    }

    /// Exercises in the lesson: the `total` of `n / total`.
    var exerciseTotal: Int { entries.filter(\.isExercise).count }

    /// The exercise on screen (1-based), or how many are behind the learner on a content page.
    var exerciseNumber: Int {
        let end = min(current?.isExercise == true ? position + 1 : position, entries.count)
        return entries[..<end].filter(\.isExercise).count
    }

    var progress: Double {
        guard exerciseTotal > 0 else { return isFinished ? 1 : Double(position) / Double(max(entries.count, 1)) }
        let done = entries[..<min(position, entries.count)].filter(\.isExercise).count
        return Double(done) / Double(exerciseTotal)
    }

    /// Which steps a move finished and entered: the player writes `stepCompleted` and `stepStarted` from it
    /// (`Progression.shouldWriteStepStarted` decides whether a revisit writes again).
    struct StepChange: Sendable, Equatable {
        var completed: StepID?
        var started: StepID?
    }

    /// The step the player opens on (its `stepStarted`).
    var openingStep: StepID? { currentStep?.id }

    /// Continue: the next page, or the end of the lesson.
    @discardableResult
    func advance() -> StepChange {
        guard !isFinished, let before = current else { return StepChange() }
        if position + 1 < entries.count {
            position += 1
        } else {
            position = entries.count
            isFinished = true
        }
        let after = current
        guard after?.stepIndex != before.stepIndex else { return StepChange() }
        return StepChange(completed: bundle.steps[before.stepIndex].id,
                          started: after.map { bundle.steps[$0.stepIndex].id })
    }

    /// Exercises that the current page's step lists, for exercises shown next to their text (reading).
    var stepExercises: [ExerciseID] {
        guard let step = currentStep else { return [] }
        return step.payload.exerciseOrder(stepID: step.id)
    }

    // MARK: - Flattening and resume

    static func flatten(_ bundle: LessonBundle) -> [Entry] {
        var out: [Entry] = []
        for (i, step) in bundle.steps.enumerated() {
            func add(_ page: PlayerPage) { out.append(Entry(stepIndex: i, page: page)) }
            func addExercises(_ ids: [ExerciseID]) { ids.forEach { add(.exercise($0)) } }
            switch step.payload {
            case .opener(let unit):
                add(.opener(unit))
            case .preview(let batches):
                for batch in batches {
                    if !batch.itemIds.isEmpty { add(.meet(batch.itemIds)) }
                    addExercises(batch.exerciseIds)
                }
            case .story(let text, let questions):
                add(.story(text))
                addExercises(questions)
            case .listening(let text, let plays, let exercises):
                add(.listening(text, plays: plays))
                addExercises(exercises)
                add(.transcript(text))
            case .reading(let text, let exercises):
                add(.reading(text))
                addExercises(exercises)
            case .note(let note):
                add(.note(note))
            case .practice, .sounds, .single:
                addExercises(step.payload.exerciseOrder(stepID: step.id))
            case .check(_, _, let sections):
                for section in sections {
                    add(.checkSection(id: section.id, title: section.titleEn))
                    addExercises(section.exerciseIds)
                }
            case .fluency(let texts, let rate):
                add(.fluency(texts, rate: rate))
            }
        }
        return out
    }

    /// Resume at the first unanswered exercise; when its step was already started, go straight to the exercise,
    /// otherwise to the step's first page (so a story is read before its questions). With nothing left to answer,
    /// resume after the last answered exercise (trailing notes and fluency still play).
    static func resumePosition(entries: [Entry], answered: Set<ExerciseID>) -> Int {
        guard !answered.isEmpty else { return 0 }
        func isAnswered(_ e: Entry) -> Bool {
            if case .exercise(let id) = e.page { return answered.contains(id) }
            return false
        }
        if let i = entries.firstIndex(where: { $0.isExercise && !isAnswered($0) }) {
            let step = entries[i].stepIndex
            let stepStarted = entries.contains { $0.stepIndex == step && isAnswered($0) }
            if stepStarted { return i }
            return entries.firstIndex { $0.stepIndex == step } ?? i
        }
        guard let last = entries.lastIndex(where: isAnswered) else { return 0 }
        return last + 1
    }
}

extension LessonPlayerModel.Entry {
    var isExercise: Bool { if case .exercise = page { true } else { false } }
}

/// The word panel's content for a tapped token (docs/06 §2): the item's display form, "pos · gloss" (the token's
/// context gloss wins over the item's), the item's note, and its audio.
struct GlossContent: Sendable, Equatable {
    let headword: String
    let posAndGloss: String
    let note: String?
    let itemID: ItemID?
    let audioID: AudioID?
}

extension LessonBundle {
    /// Nil for tokens that aren't words, and for words with neither an item nor a gloss.
    func gloss(text id: TextID, line: Int, token: Int) -> GlossContent? {
        guard let line = texts[id]?.lines.first(where: { $0.number == line }),
              let t = line.text.tokens[safe: token], t.kind == .word
        else { return nil }
        let info = t.itemId.flatMap { items[$0] }
        guard let gloss = t.gloss ?? info?.gloss else { return nil }
        let pos = info?.partOfSpeech
        return GlossContent(
            headword: info?.display ?? t.surface, posAndGloss: pos.map { "\($0) · \(gloss)" } ?? gloss,
            note: info?.note, itemID: t.itemId, audioID: info?.audioID)
    }

    /// "New in this story": the items of tokens flagged new, once each, in reading order.
    func newWords(in id: TextID) -> [WordInfo] {
        var seen: Set<ItemID> = []
        var out: [WordInfo] = []
        for line in texts[id]?.lines ?? [] {
            for t in line.text.tokens where t.flags & 1 != 0 {
                guard let item = t.itemId, !seen.contains(item), let info = items[item] else { continue }
                seen.insert(item)
                out.append(info)
            }
        }
        return out
    }
}

extension LayoutPayload {
    /// Every string of the layout in reading order. Its 1-based position is the "line" of a gloss tapped in it
    /// (`glossTapped.line`, `reading.field.<n>`), so taps on real-world texts are logged like story taps.
    var strings: [LayoutString] {
        switch self {
        case .menu(let title, let sections):
            [title] + sections.flatMap { section in
                [section.title] + section.rows.flatMap { [$0.name, $0.price] + [$0.note].compactMap { $0 } }
            }
        case .receipt(let shop, let rows, let total, let footer):
            [shop] + rows.flatMap { [$0.name] + [$0.qty].compactMap { $0 } + [$0.price] } + [total]
                + [footer].compactMap { $0 }
        case .sign(let lines, _):
            lines
        case .hours(let title, let rows, let note):
            [title] + rows.flatMap { [$0.days, $0.times] } + [note].compactMap { $0 }
        case .timetable(let title, let columns, let rows):
            [title] + columns + rows.flatMap { $0 }
        case .fields(_, let title, let fields):
            [title] + fields.flatMap { [$0.label, $0.value] }
        case .ad(let title, let body, let contact):
            [title] + body + [contact].compactMap { $0 }
        case .message(let from, let time, let bubbles):
            [from] + [time].compactMap { $0 } + bubbles
        case .postcard(let greeting, let body, let closing, let signature, let address):
            [greeting] + body + [closing, signature] + (address ?? [])
        case .list(let title, let items):
            [title].compactMap { $0 } + items
        }
    }

    /// The first position of each string (a repeated price shares the first one's number).
    var stringNumbers: [LayoutString: Int] {
        var out: [LayoutString: Int] = [:]
        for (i, s) in strings.enumerated() where out[s] == nil { out[s] = i + 1 }
        return out
    }
}

/// The text an exercise refers to (`source`, docs/06 § Building-block formats).
struct SourceText: Sendable, Equatable {
    let text: PlayerText
    /// 1-based; nil for the whole text.
    var line: Int?
}

extension LessonBundle {
    /// The text an exercise shows above its question: its `source`, or a relay's source text (docs/06 §15).
    func source(for p: ExercisePayload) -> SourceText? {
        if let ref = p.source, let text = texts[ref.textId] { return SourceText(text: text, line: ref.line) }
        if case .relay(let r) = p.body, let id = r.sourceTextId, let text = texts[id] { return SourceText(text: text) }
        return nil
    }
}
