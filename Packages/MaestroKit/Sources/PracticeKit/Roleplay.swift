import Foundation
import PackKit

/// A role-play (HANDOFF.md 3.9): the other side's lines play out, and at each of the learner's turns
/// they pick a reply chip or type one. A first miss allows another try; a second shows the text's line
/// ("You could say") and the conversation goes on. A goal is reached when its turn is answered. Pure, so
/// the app's view only renders it.
public struct RoleplayState: Sendable, Equatable {
    public struct Line: Sendable, Equatable {
        public let who: String
        public let text: String
        public let isLearner: Bool
        /// The learner's line was shown, not answered.
        public let shown: Bool
    }

    public let turns: [RoleplayTurn]
    public let german: Bool
    /// The lines so far, the other side's and the learner's.
    public private(set) var transcript: [Line] = []
    /// The turn waiting for the learner, or nil when it's over.
    public private(set) var current: Int?
    /// Wrong chips picked at the current turn.
    public private(set) var wrongChips: Set<String> = []
    public private(set) var hint: String?
    public private(set) var reached: Set<String> = []
    private var outcomes: [Outcome] = []
    private var missed = false

    /// `text(sentenceIDs)` gives a turn's words from the text.
    public init(drill: Drill, text: @escaping @Sendable ([String]) -> String) {
        turns = drill.turns ?? []
        german = drill.isGerman
        self.lineText = text
        advance(from: 0)
    }

    private let lineText: @Sendable ([String]) -> String

    public static func == (a: RoleplayState, b: RoleplayState) -> Bool {
        a.transcript == b.transcript && a.current == b.current && a.wrongChips == b.wrongChips
            && a.hint == b.hint && a.reached == b.reached && a.outcomes == b.outcomes
    }

    public var isDone: Bool { current == nil }

    /// The chips of the current turn, in a stable order.
    public func chips(seed: String) -> [String] {
        guard let n = current else { return [] }
        return SeededShuffle.shuffled(turns[n].chips ?? [], seed: "\(seed).\(n)")
    }

    /// The worst of the turns' outcomes: a first try only if every turn was.
    public var outcome: Outcome {
        if outcomes.contains(.shown) { return .shown }
        if outcomes.contains(.afterHint) { return .afterHint }
        return .firstTry
    }

    /// A picked chip.
    public mutating func pick(_ chip: String) {
        guard let n = current else { return }
        if (turns[n].answers ?? []).contains(chip) {
            answer(n, with: chip)
        } else {
            wrongChips.insert(chip)
            miss(n)
        }
    }

    /// A typed reply, graded by the turn's patterns.
    @discardableResult
    public mutating func say(_ reply: String) -> Grade {
        guard let n = current else { return .correct }
        let patterns = (turns[n].accept ?? []) + (turns[n].answers ?? [])
        let grade = PatternGrader.grade(reply, patterns: patterns, german: german)
        switch grade {
        case .correct: answer(n, with: reply.trimmingCharacters(in: .whitespaces))
        case .accentSlip(let expected): answer(n, with: expected)
        case .wrong: miss(n)
        }
        return grade
    }

    /// "Show me": the text's line, and on to the next turn.
    public mutating func reveal() {
        guard let n = current else { return }
        show(n)
    }

    private mutating func answer(_ n: Int, with words: String) {
        transcript.append(Line(who: turns[n].who, text: words, isLearner: true, shown: false))
        outcomes.append(missed ? .afterHint : .firstTry)
        if let goal = turns[n].goal { reached.insert(goal) }
        advance(from: n + 1)
    }

    private mutating func miss(_ n: Int) {
        if missed {
            show(n)
        } else {
            missed = true
            hint = "That doesn't fit here. Read what \(previousSpeaker(n) ?? "they") said again."
        }
    }

    private mutating func show(_ n: Int) {
        transcript.append(Line(who: turns[n].who, text: turns[n].answers?.first ?? lineText(turns[n].s),
                               isLearner: true, shown: true))
        outcomes.append(.shown)
        advance(from: n + 1)
    }

    private func previousSpeaker(_ n: Int) -> String? {
        turns[..<n].last { !$0.isLearner }?.who
    }

    /// Plays the other side's lines up to the learner's next turn.
    private mutating func advance(from start: Int) {
        wrongChips = []
        hint = nil
        missed = false
        var n = start
        while n < turns.count && !turns[n].isLearner {
            transcript.append(Line(who: turns[n].who, text: lineText(turns[n].s), isLearner: false, shown: false))
            n += 1
        }
        current = n < turns.count ? n : nil
    }
}
