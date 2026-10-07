import Foundation

/// Which (item, skill) pairs get introduced, and how (docs/05 § Introductions and eligibility).
public enum Introductions {
    /// The `via` a step kind writes at step start; nil for kinds that never introduce.
    public static func via(for kind: StepKind) -> IntroductionVia? {
        switch kind {
        case .preview: .preview
        case .story, .listening, .reading: .story
        case .note: .note
        case .sounds: .sounds
        default: nil
        }
    }

    /// The skills a whole item is introduced for "per its status" (preview batches, placement): words and chunks
    /// get read and listen, plus recall and speak where that skill's status is P; grammar points read, plus recall
    /// if P; sounds listen.
    public static func standardSkills(for item: ContentIndex.Item) -> [Skill] {
        switch item.kind {
        case .word, .chunk:
            return [.read, .listen] + [Skill.recall, .speak].filter { item.status($0) == .P }
        case .grammar:
            return [.read] + (item.status(.recall) == .P ? [.recall] : [])
        case .sound:
            return [.listen]
        }
    }

    /// The pairs a step introduces (`step_introduces`) that the learner hasn't met yet, sorted. Steps of kinds that
    /// never introduce yield nothing.
    public static func pending(step: ContentIndex.Step, state: LearnerState) -> [ItemSkillPair] {
        guard via(for: step.kind) != nil else { return [] }
        return Set(step.introduces).filter { !state.isIntroduced($0) }.sorted()
    }

    /// Placement: every item in units before the start unit, per its status (docs/05 § Placement), as one
    /// `introduced` payload (via `placement`), or nil when there is nothing to introduce.
    public static func placementPayload(startUnit: UnitID, content: ContentIndex) -> IntroducedPayload? {
        guard let startOrd = content.unitOrd(startUnit) else { return nil }
        var pairs: [ItemSkillPair] = []
        for unit in content.units where unit.ord < startOrd {
            for item in content.items(in: unit.id) {
                pairs += standardSkills(for: item).map { ItemSkillPair(item.id, $0) }
            }
        }
        guard !pairs.isEmpty else { return nil }
        return IntroducedPayload(pairs: pairs, via: .placement)
    }
}

/// docs/05 § Introductions applied to raw course data. The pipeline precomputes `step_introduces` from these rules;
/// this helper states them in Swift (tests, tools) and must agree with the pack.
public enum IntroductionRules {
    public struct RawItem: Hashable, Sendable {
        public var id: ItemID
        public var kind: ItemKind
        public var unitId: UnitID
        /// Status per skill (`item_skills`).
        public var skills: [Skill: ItemStatus]
        /// Grammar points: `points.yaml` status (P, R or chunk).
        public var grammarStatus: ItemStatus?
        /// Chunks: the grammar points they exemplify.
        public var exemplifies: [ItemID]

        public init(id: ItemID, kind: ItemKind? = nil, unitId: UnitID, skills: [Skill: ItemStatus] = [:],
                    grammarStatus: ItemStatus? = nil, exemplifies: [ItemID] = [])
        {
            self.id = id
            self.kind = kind ?? id.kind ?? .word
            self.unitId = unitId
            self.skills = skills
            self.grammarStatus = grammarStatus
            self.exemplifies = exemplifies
        }
    }

    public struct RawStep: Hashable, Sendable {
        public var id: StepID
        public var unitId: UnitID
        public var kind: StepKind
        /// Preview: every batch item.
        public var previewItems: [ItemID]
        /// Story, listening, reading: items flagged new in the text.
        public var newTextItems: [ItemID]
        /// Note: its `grammar` list (`note_items`).
        public var noteGrammar: [ItemID]
        /// Sounds: the sound item.
        public var soundItems: [ItemID]
        /// Story, listening: grammar points detected in the text.
        public var detectedGrammar: [ItemID]

        public init(id: StepID, unitId: UnitID, kind: StepKind, previewItems: [ItemID] = [],
                    newTextItems: [ItemID] = [], noteGrammar: [ItemID] = [], soundItems: [ItemID] = [],
                    detectedGrammar: [ItemID] = [])
        {
            self.id = id
            self.unitId = unitId
            self.kind = kind
            self.previewItems = previewItems
            self.newTextItems = newTextItems
            self.noteGrammar = noteGrammar
            self.soundItems = soundItems
            self.detectedGrammar = detectedGrammar
        }
    }

    /// `step_introduces` for steps given in course order.
    ///
    /// - preview: each batch item, read and listen, plus recall and speak where that skill's status is P;
    /// - story, listening, reading: items flagged new in the text, read and listen;
    /// - note: each grammar point in its list, read, plus recall if P;
    /// - sounds: the sound item, listen;
    /// - a grammar point with status R or chunk is introduced (read only) by the earliest of: its note; the first
    ///   preview in its own unit containing a chunk that exemplifies it; or else the first story or listening step
    ///   of its unit where it is detected. A chunk from an earlier unit never introduces a later point.
    public static func stepIntroduces(steps: [RawStep], items: [ItemID: RawItem]) -> [StepID: [ItemSkillPair]] {
        var result: [StepID: Set<ItemSkillPair>] = [:]
        var firstStepOfGrammar: [ItemID: Int] = [:]  // R/chunk points: earliest note

        func status(_ item: RawItem, _ skill: Skill) -> ItemStatus? { item.skills[skill] }

        for (index, step) in steps.enumerated() {
            switch step.kind {
            case .preview:
                for id in step.previewItems {
                    guard let item = items[id], item.kind != .grammar else { continue }
                    let skills: [Skill] =
                        item.kind == .sound
                        ? [.listen] : [.read, .listen] + [Skill.recall, .speak].filter { status(item, $0) == .P }
                    for skill in skills { result[step.id, default: []].insert(ItemSkillPair(id, skill)) }
                }
            case .story, .listening, .reading:
                for id in step.newTextItems {
                    guard let item = items[id], item.kind != .grammar else { continue }
                    result[step.id, default: []].insert(ItemSkillPair(id, .read))
                    result[step.id, default: []].insert(ItemSkillPair(id, .listen))
                }
            case .note:
                for id in step.noteGrammar {
                    guard let item = items[id] else { continue }
                    if item.grammarStatus == .P {
                        result[step.id, default: []].insert(ItemSkillPair(id, .read))
                        result[step.id, default: []].insert(ItemSkillPair(id, .recall))
                    } else if firstStepOfGrammar[id] == nil {
                        firstStepOfGrammar[id] = index
                    }
                }
            case .sounds:
                for id in step.soundItems { result[step.id, default: []].insert(ItemSkillPair(id, .listen)) }
            default:
                break
            }
        }

        // R and chunk points: the earliest of the note, an exemplifying preview in its own unit, or else a story
        // or listening step of its unit where it is detected.
        for point in items.values.sorted(by: { $0.id < $1.id })
        where point.kind == .grammar && (point.grammarStatus == .R || point.grammarStatus == .chunk) {
            let preview = steps.firstIndex { step in
                step.kind == .preview && step.unitId == point.unitId
                    && step.previewItems.contains { items[$0]?.exemplifies.contains(point.id) == true }
            }
            let story =
                preview == nil
                ? steps.firstIndex { step in
                    (step.kind == .story || step.kind == .listening) && step.unitId == point.unitId
                        && step.detectedGrammar.contains(point.id)
                } : nil
            let candidates = [firstStepOfGrammar[point.id], preview, story].compactMap { $0 }
            guard let earliest = candidates.min() else { continue }
            result[steps[earliest].id, default: []].insert(ItemSkillPair(point.id, .read))
        }
        return result.mapValues { $0.sorted() }
    }
}
