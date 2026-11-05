import Foundation
import PackKit

/// How long a session is: Short keeps each strand's `core` drills.
public enum SessionLength: String, Sendable, Hashable, CaseIterable {
    case short, full
}

/// The learner's choices on the plan screen (HANDOFF.md 3.9).
public struct SessionSettings: Sendable, Hashable {
    public var length: SessionLength
    /// The strands switched on.
    public var strands: Set<Strand>
    public var questions: Bool
    public var review: Bool

    public init(length: SessionLength = .full, strands: Set<Strand> = Set(Strand.allCases), questions: Bool = true,
                review: Bool = true) {
        self.length = length
        self.strands = strands
        self.questions = questions
        self.review = review
    }
}

/// A stage of a session after the reading, in the order the session runs them.
public enum StageKind: String, Sendable, Hashable, CaseIterable, Identifiable {
    case questions, words, grammar, verbs, say, review

    public var id: String { rawValue }

    public var strand: Strand? {
        switch self {
        case .words: .words
        case .grammar: .grammar
        case .verbs: .verbs
        case .say: .say
        case .questions, .review: nil
        }
    }

    public var title: String {
        switch self {
        case .questions: "Questions"
        case .words: "Words"
        case .grammar: "Grammar"
        case .verbs: "Verbs"
        case .say: "Say it"
        case .review: "Review"
        }
    }
}

/// A drill in a session: from this text, or from an earlier one for Review.
public struct SessionDrill: Sendable, Hashable, Identifiable {
    public let textID: String
    public let drill: Drill

    public init(textID: String, drill: Drill) {
        self.textID = textID
        self.drill = drill
    }

    /// Unique in a session, and the key its outcome is stored under.
    public var id: String { "\(textID)|\(drill.stableKey)" }
}

public struct SessionStage: Sendable, Hashable, Identifiable {
    public let kind: StageKind
    public let drills: [SessionDrill]
    /// The stage opens with the grammar point's intro, because it drills the point and the Grammar
    /// stage, which would have introduced it, is off.
    public let introducesGrammar: Bool

    public var id: StageKind { kind }

    public init(kind: StageKind, drills: [SessionDrill], introducesGrammar: Bool = false) {
        self.kind = kind
        self.drills = drills
        self.introducesGrammar = introducesGrammar
    }
}

/// Builds a session from a text's drills (HANDOFF.md 3.9). Pure, so every device builds the same one.
///
/// Order: Questions, Words, Grammar, Verbs, Say it, Review. A drill on a form of the topic the text
/// introduces never comes before that topic's intro: such a drill in an earlier stage moves to the
/// Verbs stage (or is left out when Verbs is off), and when Grammar is off, the first stage after it that drills the topic opens with the
/// intro instead.
public enum SessionBuilder {
    public static let reviewLimit = 3

    public static func stages(textID: String, drills: [Drill], hasQuestions: Bool, introduces: [String],
                              settings: SessionSettings, review: [SessionDrill] = []) -> [SessionStage] {
        let known = drills.filter { $0.format != nil }
        var byStrand: [Strand: [Drill]] = [:]
        for drill in known { byStrand[drill.strandKind, default: []].append(drill) }

        var plan: [(StageKind, [Drill])] = []
        if hasQuestions && settings.questions { plan.append((.questions, [])) }
        for kind in [StageKind.words, .grammar, .verbs, .say] {
            guard let strand = kind.strand, settings.strands.contains(strand) else { continue }
            let chosen = pick(byStrand[strand] ?? [], length: settings.length)
            if !chosen.isEmpty { plan.append((kind, chosen)) }
        }

        // Nothing on the introduced topic before the Grammar stage.
        let introduced = Set(introduces)
        let grammarAt = plan.firstIndex { $0.0 == .grammar }
        let cut = grammarAt ?? plan.firstIndex { $0.0 == .verbs || $0.0 == .say } ?? plan.count
        var moved: [Drill] = []
        for n in plan.indices where n < cut && plan[n].0 != .grammar {
            moved += plan[n].1.filter { introduced.contains($0.topic) }
            plan[n].1.removeAll { introduced.contains($0.topic) }
        }
        if !moved.isEmpty {
            if let v = plan.firstIndex(where: { $0.0 == .verbs }) {
                plan[v].1 = moved + plan[v].1
            } else if settings.strands.contains(.verbs) {
                plan.insert((.verbs, moved), at: grammarAt.map { $0 + 1 } ?? cut)
            }
        }
        plan.removeAll { $0.0 != .questions && $0.1.isEmpty }

        var stages = plan.map { step in
            SessionStage(kind: step.0, drills: step.1.map { SessionDrill(textID: textID, drill: $0) })
        }
        if grammarAt == nil, !introduced.isEmpty,
           let first = stages.firstIndex(where: { $0.drills.contains { introduced.contains($0.drill.topic) } }) {
            stages[first] = SessionStage(kind: stages[first].kind, drills: stages[first].drills, introducesGrammar: true)
        }
        if settings.review && !review.isEmpty {
            stages.append(SessionStage(kind: .review, drills: Array(review.prefix(reviewLimit))))
        }
        return stages
    }

    /// How many drills each strand has, in a Short and a Full session, for the plan screen.
    public static func counts(_ drills: [Drill]) -> [Strand: (short: Int, full: Int)] {
        var out: [Strand: (short: Int, full: Int)] = [:]
        for strand in Strand.allCases {
            let own = drills.filter { $0.format != nil && $0.strandKind == strand }
            if !own.isEmpty { out[strand] = (pick(own, length: .short).count, own.count) }
        }
        return out
    }

    /// A strand's drills for a length: Short keeps its core drills, or its first two when none is.
    static func pick(_ drills: [Drill], length: SessionLength) -> [Drill] {
        guard length == .short else { return drills }
        let core = drills.filter(\.isCore)
        return core.isEmpty ? Array(drills.prefix(2)) : core
    }
}

// MARK: Outcomes and review

/// One stored outcome of a drill.
public struct DrillRecord: Sendable, Hashable {
    public let textID: String
    public let drillKey: String
    public let outcome: Outcome
    public let at: Date

    public init(textID: String, drillKey: String, outcome: Outcome, at: Date) {
        self.textID = textID
        self.drillKey = drillKey
        self.outcome = outcome
        self.at = at
    }
}

/// The Review stage: drills from earlier sessions that needed help.
public enum ReviewPicker {
    /// Up to `limit` drills of other texts whose latest outcome wasn't a first try, most recent first.
    /// A drill answered on the first try in a review drops out; one that needed help again stays.
    public static func pick(_ records: [DrillRecord], excluding textID: String,
                            limit: Int = SessionBuilder.reviewLimit) -> [DrillRecord] {
        var latest: [String: DrillRecord] = [:]
        for r in records where r.textID != textID {
            let id = "\(r.textID)|\(r.drillKey)"
            if let seen = latest[id], seen.at >= r.at { continue }
            latest[id] = r
        }
        return latest.values
            .filter { $0.outcome != .firstTry }
            .sorted { ($0.at, $0.textID, $0.drillKey) > ($1.at, $1.textID, $1.drillKey) }
            .prefix(limit)
            .map { $0 }
    }

    /// Whether a drill can come back in Review: a role-play is too long to.
    /// A drill without a stable `key` (from a pack built before keys) can't either: its `d<n>` ID may
    /// name another drill after a rebuild.
    public static func canReview(_ drill: Drill) -> Bool {
        drill.key != nil && drill.format != nil && drill.format != .roleplay
    }
}
