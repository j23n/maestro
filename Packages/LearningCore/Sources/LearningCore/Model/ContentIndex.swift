import Foundation

public enum CheckTag {}
/// `uNN.check` for unit checks, `final` for the final A1 check (docs/03 § IDs).
public typealias CheckID = TypedID<CheckTag>

/// One (item, skill) pair. Memory, introductions, requirements, targets and focus items are all keyed by it.
public struct ItemSkillPair: Hashable, Comparable, Codable, Sendable, CustomStringConvertible {
    public var itemId: ItemID
    public var skill: Skill

    public init(_ itemId: ItemID, _ skill: Skill) {
        self.itemId = itemId
        self.skill = skill
    }

    /// Sorted by `(itemId, skill)` with skills in the order read, listen, recall, speak.
    public static func < (lhs: Self, rhs: Self) -> Bool {
        lhs.itemId != rhs.itemId ? lhs.itemId < rhs.itemId : lhs.skill < rhs.skill
    }

    public var description: String { "\(itemId.rawValue)/\(skill.rawValue)" }
}

/// `units.kind` in the pack: Units 0–12 are `unit`, the final review `u99` is `final`.
public enum UnitKind: String, Codable, Sendable {
    case unit, final
}

/// `steps.strand` in the pack (Nation's four strands plus assessment).
public enum Strand: String, Codable, Sendable {
    case input, output
    case languageFocus = "language-focus"
    case fluency, assessment
}

/// `items.gender` in the pack.
public enum Gender: String, Codable, Sendable {
    case m, f, mf
}

/// The read-only view of the content pack that the learning engine needs (`schemas/content-pack.sql`).
///
/// A plain value: Storage builds it from the pack's tables, tests fill it by hand. It holds IDs, relations and the
/// few item fields the engine reads (generated cards, eligibility, planning), never exercise payloads.
public struct ContentIndex: Sendable {
    /// `units` row.
    public struct Unit: Hashable, Sendable {
        public var id: UnitID
        public var ord: Int
        public var kind: UnitKind

        public init(id: UnitID, ord: Int, kind: UnitKind = .unit) {
            self.id = id
            self.ord = ord
            self.kind = kind
        }
    }

    /// `lessons` row.
    public struct Lesson: Hashable, Sendable {
        public var id: LessonID
        public var unitId: UnitID
        public var ord: Int

        public init(id: LessonID, unitId: UnitID, ord: Int) {
            self.id = id
            self.unitId = unitId
            self.ord = ord
        }
    }

    /// `steps` row plus what its payload references (docs/06 § Payloads) and its `step_introduces` rows.
    public struct Step: Hashable, Sendable {
        public let id: StepID
        public let unitId: UnitID
        public let lessonId: LessonID?
        /// Order within the unit; course order is `(units.ord, steps.ord)`.
        public let ord: Int
        public let kind: StepKind
        public let strand: Strand
        /// Every exercise the step holds, as written: preview `exerciseIds` batch by batch, story `questionIds`,
        /// listening, reading and sounds `exerciseIds`, use and task steps' `exerciseId`, check sections in order,
        /// practice `block` then `mix`.
        public let exerciseIds: [ExerciseID]
        /// Practice steps only: the block, in file order.
        public let block: [ExerciseID]
        /// Practice steps only: the mix as written (the player shuffles it, seeded by the step ID).
        public let mix: [ExerciseID]
        /// Texts the step shows (story, listening and reading `textId`; fluency `textIds`).
        public let textIds: [TextID]
        /// Note steps: the note.
        public let noteId: NoteID?
        /// Check steps: the check.
        public let checkId: CheckID?
        /// `step_introduces`: the (item, skill) pairs this step introduces at step start (docs/05 § Introductions).
        public let introduces: [ItemSkillPair]
        /// The order the player presents the exercises in (docs/05 § Replay): the block in file order, then the
        /// mix shuffled with SplitMix64 seeded by FNV-1a 64 of the step ID; every other kind as written.
        public let presentationOrder: [ExerciseID]

        public init(id: StepID, unitId: UnitID, lessonId: LessonID? = nil, ord: Int, kind: StepKind,
                    strand: Strand = .languageFocus, exerciseIds: [ExerciseID] = [], block: [ExerciseID] = [],
                    mix: [ExerciseID] = [], textIds: [TextID] = [], noteId: NoteID? = nil, checkId: CheckID? = nil,
                    introduces: [ItemSkillPair] = [])
        {
            self.id = id
            self.unitId = unitId
            self.lessonId = lessonId
            self.ord = ord
            self.kind = kind
            self.strand = strand
            self.block = block
            self.mix = mix
            self.exerciseIds = kind == .practice && exerciseIds.isEmpty ? block + mix : exerciseIds
            self.textIds = textIds
            self.noteId = noteId
            self.checkId = checkId
            self.introduces = introduces
            self.presentationOrder =
                kind == .practice ? block + mix.seededShuffle(seed: id.rawValue) : self.exerciseIds
        }
    }

    /// One `item_skills` row.
    public struct SkillInfo: Hashable, Sendable {
        public var status: ItemStatus
        public var scheduled: Bool

        public init(status: ItemStatus, scheduled: Bool) {
            self.status = status
            self.scheduled = scheduled
        }
    }

    /// `items` row with its `item_skills`.
    public struct Item: Hashable, Sendable {
        public var id: ItemID
        public var kind: ItemKind
        /// Lemma, chunk text, grammar title or sound label.
        public var it: String
        public var gloss: String
        public var altGlosses: [String]
        public var pos: String?
        public var gender: Gender?
        /// Nouns: `il cornetto`, `l'acqua (f)`, `l'amico / l'amica` (the display form, docs/03).
        public var displayDef: String?
        /// Nouns: `un cornetto` (used in generated answers).
        public var displayIndef: String?
        /// Answer pattern for generated recall cards, or nil for the default (docs/05 § Review session builder).
        public var recallAnswer: String?
        public var topics: [String]
        public var unitId: UnitID
        public var lessonId: LessonID?
        public var skills: [Skill: SkillInfo]

        public init(id: ItemID, kind: ItemKind? = nil, it: String, gloss: String, altGlosses: [String] = [],
                    pos: String? = nil, gender: Gender? = nil, displayDef: String? = nil, displayIndef: String? = nil,
                    recallAnswer: String? = nil, topics: [String] = [], unitId: UnitID, lessonId: LessonID? = nil,
                    skills: [Skill: SkillInfo] = [:])
        {
            self.id = id
            self.kind = kind ?? id.kind ?? .word
            self.it = it
            self.gloss = gloss
            self.altGlosses = altGlosses
            self.pos = pos
            self.gender = gender
            self.displayDef = displayDef
            self.displayIndef = displayIndef
            self.recallAnswer = recallAnswer
            self.topics = topics
            self.unitId = unitId
            self.lessonId = lessonId
            self.skills = skills
        }

        /// The gloss up to the first `;` (prompts of generated recall cards, options of generated read cards).
        public var primaryGloss: String {
            let head = gloss.split(separator: ";", maxSplits: 1, omittingEmptySubsequences: false).first ?? ""
            return head.trimmingCharacters(in: .whitespaces)
        }

        /// The form cards show: the noun's display form, otherwise the lemma or chunk text.
        public var displayForm: String { displayDef ?? it }

        /// Skills with `item_skills.scheduled = 1`, in skill order.
        public var scheduledSkills: [Skill] {
            skills.filter { $0.value.scheduled }.map(\.key).sorted()
        }

        public func status(_ skill: Skill) -> ItemStatus? { skills[skill]?.status }
    }

    /// `exercises` row with its `exercise_targets`, `exercise_tags` and `exercise_requires`.
    public struct Exercise: Hashable, Sendable {
        public var id: ExerciseID
        public var format: ExerciseFormat
        public var unitId: UnitID
        public var stepId: StepID?
        public var role: ExerciseRole
        /// Points in checks (default 1).
        public var score: Int
        /// Primary targets, in order (`match`: `targets[i]` belongs to `pairs[i]`).
        public var targets: [ItemSkillPair]
        /// `cd:…` and `sy:…` tags.
        public var tags: [String]
        /// `exercise_requires`: what eligibility checks.
        public var requires: [ItemSkillPair]

        public init(id: ExerciseID, format: ExerciseFormat, unitId: UnitID, stepId: StepID? = nil,
                    role: ExerciseRole = .learn, score: Int = 1, targets: [ItemSkillPair] = [], tags: [String] = [],
                    requires: [ItemSkillPair] = [])
        {
            self.id = id
            self.format = format
            self.unitId = unitId
            self.stepId = stepId
            self.role = role
            self.score = score
            self.targets = targets
            self.tags = tags
            self.requires = requires
        }

        public var canDoTags: [CanDoID] { tags.filter { $0.hasPrefix("cd:") }.map { CanDoID($0) } }
    }

    /// `texts` row with its `text_requires`.
    public struct Text: Hashable, Sendable {
        public var id: TextID
        public var unitId: UnitID
        public var requires: [ItemSkillPair]

        public init(id: TextID, unitId: UnitID, requires: [ItemSkillPair] = []) {
            self.id = id
            self.unitId = unitId
            self.requires = requires
        }
    }

    /// `grammar_notes` row with its `note_items` in `ord` order.
    public struct Note: Hashable, Sendable {
        public var id: NoteID
        public var stepId: StepID
        public var itemIds: [ItemID]

        public init(id: NoteID, stepId: StepID, itemIds: [ItemID]) {
            self.id = id
            self.stepId = stepId
            self.itemIds = itemIds
        }
    }

    /// `can_dos` row.
    public struct CanDo: Hashable, Sendable {
        public var id: CanDoID
        public var unitId: UnitID
        public var ord: Int

        public init(id: CanDoID, unitId: UnitID, ord: Int) {
            self.id = id
            self.unitId = unitId
            self.ord = ord
        }
    }

    /// A check section: its ID and exercises in order.
    public struct CheckSection: Hashable, Sendable {
        public var id: String
        public var exerciseIds: [ExerciseID]
        /// Final check only: the section's points (12).
        public var max: Double?

        public init(id: String, exerciseIds: [ExerciseID], max: Double? = nil) {
            self.id = id
            self.exerciseIds = exerciseIds
            self.max = max
        }
    }

    /// A unit check (the `check` step payload, docs/06 § Unit-level steps).
    public struct Check: Hashable, Sendable {
        public var id: CheckID
        public var unitId: UnitID
        public var stepId: StepID?
        public var passOverall: Double
        public var sectionMin: Double
        public var sections: [CheckSection]

        public init(id: CheckID, unitId: UnitID, stepId: StepID? = nil, passOverall: Double = 0.70,
                    sectionMin: Double = 0.50, sections: [CheckSection])
        {
            self.id = id
            self.unitId = unitId
            self.stepId = stepId
            self.passOverall = passOverall
            self.sectionMin = sectionMin
            self.sections = sections
        }

        public var exerciseIds: [ExerciseID] { sections.flatMap(\.exerciseIds) }
    }

    /// The `assessments` row `placement` (docs/06 §19).
    public struct PlacementAssessment: Hashable, Sendable {
        public struct Block: Hashable, Sendable {
            public var unitId: UnitID
            public var exerciseIds: [ExerciseID]

            public init(unitId: UnitID, exerciseIds: [ExerciseID]) {
                self.unitId = unitId
                self.exerciseIds = exerciseIds
            }
        }

        /// Advance to the next block when a block scores at least this (4 of 5).
        public var advanceThreshold: Double
        public var blocks: [Block]

        public init(advanceThreshold: Double = 4, blocks: [Block]) {
            self.advanceThreshold = advanceThreshold
            self.blocks = blocks
        }
    }

    /// The `assessments` row `final` (docs/06 §20): five sections of 12 points.
    public struct FinalAssessment: Hashable, Sendable {
        public var id: CheckID
        public var sections: [CheckSection]
        public var indicativePassPerSection: Double

        public init(id: CheckID = "final", sections: [CheckSection], indicativePassPerSection: Double = 7) {
            self.id = id
            self.sections = sections
            self.indicativePassPerSection = indicativePassPerSection
        }

        public var exerciseIds: [ExerciseID] { sections.flatMap(\.exerciseIds) }
    }

    /// One word of a sound pair (`sounds.pairs`).
    public struct SoundWord: Hashable, Sendable, Codable {
        public var it: String
        public var audioId: AudioID?

        public init(it: String, audioId: AudioID? = nil) {
            self.it = it
            self.audioId = audioId
        }
    }

    /// `sounds` row.
    public struct Sound: Hashable, Sendable {
        public var itemId: ItemID
        public var pairs: [[SoundWord]]

        public init(itemId: ItemID, pairs: [[SoundWord]]) {
            self.itemId = itemId
            self.pairs = pairs
        }
    }

    public let packVersion: String
    /// `meta.content_hash`; a change triggers `rebuildAll()` (docs/05 § Replay).
    public let contentHash: String
    /// Sorted by `ord`.
    public let units: [Unit]
    public let lessons: [Lesson]
    /// Course order: `(units.ord, steps.ord)`.
    public let steps: [Step]
    /// Sorted by ID.
    public let items: [Item]
    /// Sorted by ID.
    public let exercises: [Exercise]
    public let texts: [Text]
    public let notes: [Note]
    /// Sorted by `(unit ord, ord)`.
    public let canDos: [CanDo]
    public let checks: [Check]
    public let placement: PlacementAssessment?
    public let finalCheck: FinalAssessment?
    public let sounds: [Sound]
    /// Every pair with `item_skills.scheduled = 1`, sorted.
    public let scheduledPairs: [ItemSkillPair]

    private let unitById: [UnitID: Unit]
    private let stepById: [StepID: Step]
    private let stepsByUnit: [UnitID: [Step]]
    private let itemById: [ItemID: Item]
    private let itemsByUnit: [UnitID: [Item]]
    private let exerciseById: [ExerciseID: Exercise]
    private let exercisesByTarget: [ItemSkillPair: [ExerciseID]]
    private let textById: [TextID: Text]
    private let noteById: [NoteID: Note]
    private let canDosByUnit: [UnitID: [CanDo]]
    private let checkById: [CheckID: Check]
    private let checkByUnit: [UnitID: Check]
    private let soundByItem: [ItemID: Sound]

    public init(packVersion: String = "0.0.0", contentHash: String = "", units: [Unit], lessons: [Lesson] = [],
                steps: [Step] = [], items: [Item] = [], exercises: [Exercise] = [], texts: [Text] = [],
                notes: [Note] = [], canDos: [CanDo] = [], checks: [Check] = [],
                placement: PlacementAssessment? = nil, finalCheck: FinalAssessment? = nil, sounds: [Sound] = [])
    {
        self.packVersion = packVersion
        self.contentHash = contentHash
        let sortedUnits = units.sorted { $0.ord < $1.ord }
        self.units = sortedUnits
        self.lessons = lessons.sorted { ($0.unitId.rawValue, $0.ord) < ($1.unitId.rawValue, $1.ord) }
        var unitById: [UnitID: Unit] = [:]
        for unit in sortedUnits { unitById[unit.id] = unit }
        self.unitById = unitById

        var checkById: [CheckID: Check] = [:]
        var checkByUnit: [UnitID: Check] = [:]
        for check in checks {
            checkById[check.id] = check
            checkByUnit[check.unitId] = check
        }
        self.checks = checks.sorted { $0.id < $1.id }
        self.checkById = checkById
        self.checkByUnit = checkByUnit

        // Check steps list their sections' exercises when the caller left them out.
        let filledSteps = steps.map { step -> Step in
            guard step.kind == .check, step.exerciseIds.isEmpty, let id = step.checkId, let check = checkById[id]
            else { return step }
            return Step(id: step.id, unitId: step.unitId, lessonId: step.lessonId, ord: step.ord, kind: step.kind,
                        strand: step.strand, exerciseIds: check.exerciseIds, textIds: step.textIds,
                        noteId: step.noteId, checkId: step.checkId, introduces: step.introduces)
        }
        let unitOrd = { (id: UnitID) in unitById[id]?.ord ?? Int.max }
        let orderedSteps = filledSteps.sorted {
            (unitOrd($0.unitId), $0.ord, $0.id.rawValue) < (unitOrd($1.unitId), $1.ord, $1.id.rawValue)
        }
        self.steps = orderedSteps
        var stepById: [StepID: Step] = [:]
        var stepsByUnit: [UnitID: [Step]] = [:]
        for step in orderedSteps {
            stepById[step.id] = step
            stepsByUnit[step.unitId, default: []].append(step)
        }
        self.stepById = stepById
        self.stepsByUnit = stepsByUnit

        let sortedItems = items.sorted { $0.id < $1.id }
        self.items = sortedItems
        var itemById: [ItemID: Item] = [:]
        var itemsByUnit: [UnitID: [Item]] = [:]
        var scheduled: [ItemSkillPair] = []
        for item in sortedItems {
            itemById[item.id] = item
            itemsByUnit[item.unitId, default: []].append(item)
            for skill in item.scheduledSkills { scheduled.append(ItemSkillPair(item.id, skill)) }
        }
        self.itemById = itemById
        self.itemsByUnit = itemsByUnit
        self.scheduledPairs = scheduled.sorted()

        let sortedExercises = exercises.sorted { $0.id < $1.id }
        self.exercises = sortedExercises
        var exerciseById: [ExerciseID: Exercise] = [:]
        var byTarget: [ItemSkillPair: [ExerciseID]] = [:]
        for exercise in sortedExercises {
            exerciseById[exercise.id] = exercise
            for target in Set(exercise.targets) { byTarget[target, default: []].append(exercise.id) }
        }
        self.exerciseById = exerciseById
        self.exercisesByTarget = byTarget

        self.texts = texts.sorted { $0.id < $1.id }
        var textById: [TextID: Text] = [:]
        for text in texts { textById[text.id] = text }
        self.textById = textById

        self.notes = notes.sorted { $0.id < $1.id }
        var noteById: [NoteID: Note] = [:]
        for note in notes { noteById[note.id] = note }
        self.noteById = noteById

        let sortedCanDos = canDos.sorted {
            (unitOrd($0.unitId), $0.ord, $0.id.rawValue) < (unitOrd($1.unitId), $1.ord, $1.id.rawValue)
        }
        self.canDos = sortedCanDos
        var canDosByUnit: [UnitID: [CanDo]] = [:]
        for canDo in sortedCanDos { canDosByUnit[canDo.unitId, default: []].append(canDo) }
        self.canDosByUnit = canDosByUnit

        self.placement = placement
        self.finalCheck = finalCheck
        self.sounds = sounds.sorted { $0.itemId < $1.itemId }
        var soundByItem: [ItemID: Sound] = [:]
        for sound in sounds { soundByItem[sound.itemId] = sound }
        self.soundByItem = soundByItem
    }

    // MARK: Lookups

    public func unit(_ id: UnitID) -> Unit? { unitById[id] }
    public func step(_ id: StepID) -> Step? { stepById[id] }
    public func item(_ id: ItemID) -> Item? { itemById[id] }
    public func exercise(_ id: ExerciseID) -> Exercise? { exerciseById[id] }
    public func text(_ id: TextID) -> Text? { textById[id] }
    public func note(_ id: NoteID) -> Note? { noteById[id] }
    public func sound(_ itemId: ItemID) -> Sound? { soundByItem[itemId] }

    /// A unit check by ID; `final` resolves to nothing here (see `finalCheck`).
    public func check(_ id: CheckID) -> Check? { checkById[id] }
    public func check(forUnit unitId: UnitID) -> Check? { checkByUnit[unitId] }

    /// The unit's steps in order.
    public func steps(in unitId: UnitID) -> [Step] { stepsByUnit[unitId] ?? [] }
    /// The unit's items, sorted by ID.
    public func items(in unitId: UnitID) -> [Item] { itemsByUnit[unitId] ?? [] }
    /// The unit's can-dos in order.
    public func canDos(in unitId: UnitID) -> [CanDo] { canDosByUnit[unitId] ?? [] }

    /// Exercises whose primary targets include the pair, sorted by ID.
    public func exercises(targeting pair: ItemSkillPair) -> [Exercise] {
        (exercisesByTarget[pair] ?? []).compactMap { exerciseById[$0] }
    }

    public func unitOrd(_ id: UnitID) -> Int? { unitById[id]?.ord }

    /// The unit after this one in course order.
    public func unit(after id: UnitID) -> Unit? {
        guard let ord = unitById[id]?.ord else { return nil }
        return units.first { $0.ord > ord }
    }

    /// Units 0–12 (kind `unit`): "units completed out of 13".
    public var courseUnits: [Unit] { units.filter { $0.kind == .unit } }

    /// The final review unit (`u99`), if the pack has one.
    public var finalUnit: Unit? { units.first { $0.kind == .final } }
}
