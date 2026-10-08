import Foundation
import LearningCore
import Storage

// The content pack's rows (Storage) as the App's view-model inputs. Platform-neutral; tested on Linux against the
// committed mini pack.

extension CourseOutline {
    init(_ outlines: [PackUnitOutline]) {
        self.init(units: outlines.map(CourseOutline.Unit.init))
    }
}

extension CourseOutline.Unit {
    init(_ o: PackUnitOutline) {
        let lessonSteps = Dictionary(grouping: o.steps.filter { $0.lessonId != nil }, by: { $0.lessonId })
        self.init(
            id: o.unit.id, number: Self.number(o.unit), titleIt: o.unit.titleIt, titleEn: o.unit.titleEn,
            lessons: o.lessons.sorted { $0.ord < $1.ord }.map { lesson in
                CourseOutline.Lesson(
                    id: lesson.id, titleIt: lesson.titleIt, titleEn: lesson.titleEn,
                    steps: (lessonSteps[lesson.id] ?? []).sorted { $0.ord < $1.ord }.map(CourseOutline.Step.init))
            },
            unitSteps: o.steps.filter { $0.lessonId == nil }.sorted { $0.ord < $1.ord }.map(CourseOutline.Step.init),
            summaryEn: o.canDos.sorted { $0.ord < $1.ord }.first { !$0.isStretch }?.textEn,
            canDos: o.canDos.filter { !$0.isStretch }.sorted { $0.ord < $1.ord }.map { .init(id: $0.id, en: $0.textEn) }
        )
    }

    /// `u02` → 2, `u99` → 99 (the review unit); the course order otherwise.
    static func number(_ unit: PackUnit) -> Int {
        Int(unit.id.rawValue.drop { !$0.isNumber }) ?? unit.ord
    }
}

extension CourseOutline.Step {
    init(_ s: PackStep) {
        self.init(id: s.id, kind: s.kind, titleIt: nil, titleEn: s.titleEn)
    }
}

extension WordInfo {
    init(_ item: PackItem) {
        self.init(
            itemID: item.id, display: item.display, partOfSpeech: item.pos ?? Self.kindLabel(item.kind),
            gloss: item.shortGloss, note: item.noteEn, audioID: item.audioId)
    }

    private static func kindLabel(_ kind: ItemKind) -> String {
        switch kind {
        case .word: "word"
        case .chunk: "phrase"
        case .grammar: "grammar"
        case .sound: "sound"
        }
    }
}

extension PlayerText {
    init(_ t: PackText) {
        self.init(
            id: t.id, title: t.titleIt,
            lines: t.lines.map { PlayerLine(number: $0.number, speaker: $0.speakerId, text: $0.text, english: $0.en) },
            audioID: t.audioId, layout: t.layout)
    }
}

/// Builds a `LessonBundle` from the pack: a lesson's steps, or one unit-level step (opener, task, check, fluency),
/// with every exercise, note, text, item and speaker name its pages need.
enum LessonLoader {
    static func bundle(for stepID: StepID, reader: PackReader) async throws(PackError) -> LessonBundle {
        let step = try await reader.step(stepID)
        let unit = try await reader.unit(step.unitId)
        let steps: [PackStep]
        let lessonID: LessonID
        let title: String
        if let id = step.lessonId {
            let lesson = try await reader.lesson(id)
            steps = try await reader.steps(inLesson: id).sorted { $0.ord < $1.ord }
            lessonID = id
            title = lesson.titleIt
        } else {
            steps = [step]
            lessonID = LessonID(rawValue: step.id.rawValue)
            title = step.titleEn ?? unit.titleIt
        }
        let exerciseIDs = steps.flatMap(\.exerciseOrder)
        let exercises = try await reader.exercises(exerciseIDs)
        var notes: [NoteID: NoteBody] = [:]
        var meetItems: [ItemID] = []
        for s in steps {
            switch s.payload {
            case .note(let id): notes[id] = try await reader.note(id).body
            case .preview(let batches): meetItems += batches.flatMap(\.itemIds)
            default: break
            }
        }
        let textIDs = Array(Set(steps.flatMap(\.textIds) + exercises.compactMap(\.payload.sourceTextID)))
        let texts = try await reader.texts(textIDs)
        let tokenItems = texts.flatMap(\.itemIds)
        let items = try await reader.items(Array(Set(meetItems + tokenItems)))
        let characters = try await reader.characters()
        return LessonBundle(
            lessonID: lessonID, unitID: step.unitId, title: title,
            steps: steps.map {
                LessonBundle.Step(id: $0.id, title: Self.stepTitle($0, unit: unit), payload: $0.payload)
            },
            exercises: Dictionary(exercises.map { ($0.id, $0.payload) }, uniquingKeysWith: { a, _ in a }),
            notes: notes,
            texts: Dictionary(texts.map { ($0.id, PlayerText($0)) }, uniquingKeysWith: { a, _ in a }),
            items: Dictionary(items.map { ($0.id, WordInfo($0)) }, uniquingKeysWith: { a, _ in a }),
            characters: Dictionary(characters.map { ($0.id, $0.name) }, uniquingKeysWith: { a, _ in a }))
    }

    /// "Unit 2 · Grammar"
    static func stepTitle(_ s: PackStep, unit: PackUnit) -> String {
        "Unit \(CourseOutline.Unit.number(unit)) · \(TodayCopy.kindLabel(s.kind))"
    }
}

extension ExercisePayload {
    /// The text an exercise shows or plays: its `source`, a relay's source text, or a hidden `audio_text`.
    var sourceTextID: TextID? {
        if let ref = source { return ref.textId }
        switch body {
        case .relay(let r): return r.sourceTextId ?? r.audioTextId
        case .choice(let c): return c.audioTextId
        case .trueFalse(let t): return t.audioTextId
        default: return nil
        }
    }
}
