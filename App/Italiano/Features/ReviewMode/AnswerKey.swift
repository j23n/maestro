import Foundation
import LearningCore

/// Review mode's **Answer key** (docs/04 § Review mode in the app, docs/06 § Shared player behaviour): every
/// accepted answer and near-miss of an exercise, from the pack's learner-independent pattern expansions (the same
/// expansions the review page lists), so the content lead sees what the grader takes without typing it.
struct AnswerKey: Sendable, Equatable {
    struct Entry: Sendable, Equatable {
        let text: String
        var note: String? = nil
        /// Italian text (drawn with `ItalianText`); English answers (relay, true-false) are not.
        var isItalian = true
    }

    struct Section: Sendable, Equatable {
        let title: String
        /// The authored pattern or a pass rule.
        var caption: String? = nil
        let entries: [Entry]
    }

    let exerciseID: ExerciseID
    let sections: [Section]

    init(exerciseID: ExerciseID, sections: [Section]) {
        self.exerciseID = exerciseID
        self.sections = sections
    }

    init(_ p: ExercisePayload) {
        var out: [Section] = []
        switch p.body {
        case .cloze(let c):
            out.append(Self.accepted(c.gap))
        case .recall(let r):
            out.append(Self.accepted(r.answer))
        case .repeat(let r):
            out.append(Self.accepted(r.accept))
        case .dictation(let d):
            out.append(Section(title: "Expected", entries: [Entry(text: d.say.text)]))
        case .sentenceBuilding(let s):
            out.append(Section(title: "Accepted orders", entries: s.answers.map { Entry(text: $0) }))
        case .choice(let c):
            let right = c.options[safe: c.answer]
            out.append(
                Section(
                    title: "Correct option",
                    entries: [right].compactMap { $0 }.map { Entry(text: $0.text, isItalian: $0.it != nil) }))
            let others = c.options.enumerated().filter { $0.offset != c.answer }.map(\.element)
            if !others.isEmpty {
                out.append(
                    Section(
                        title: "Other options", entries: others.map { Entry(text: $0.text, isItalian: $0.it != nil) }))
            }
        case .trueFalse(let t):
            out.append(Section(title: "Answer", entries: [Entry(text: t.answer ? "True" : "False", isItalian: false)]))
        case .soundPair(let s):
            switch s.question {
            case .whichWord:
                let word = s.play.flatMap { s.pair?[safe: $0] }
                out.append(
                    Section(title: "The word played", entries: [word].compactMap { $0 }.map { Entry(text: $0.it) }))
            case .singleOrDouble:
                let answer = s.answer == .double ? "Double" : "Single"
                out.append(
                    Section(
                        title: "Answer", entries: [Entry(text: answer, note: s.word?.it, isItalian: false)]))
            }
        case .match(let m):
            out.append(
                Section(title: "Pairs", entries: m.pairs.map { Entry(text: $0.left.text, note: $0.right) }))
        case .conversation(let c):
            for node in c.nodes where !node.expect.isEmpty {
                var entries: [Entry] = []
                for exp in node.expect {
                    let note = "intent \(exp.intent)" + (exp.goal.map { " · goal \($0)" } ?? "")
                    for pattern in exp.accept {
                        entries += Self.expansions(pattern).map { Entry(text: $0, note: note) }
                    }
                }
                entries += node.near.flatMap(Self.nearEntries)
                out.append(Section(title: "Turn \(node.id): \(node.say.text)", caption: node.hintEn, entries: entries))
            }
        case .talk(let t):
            out += Self.points(t.points, pass: t.pass)
            out.append(Section(title: "Model answer", entries: [Entry(text: t.model.text)]))
        case .writing(let w):
            for field in w.fields ?? [] {
                let accepted = (field.accept ?? []).flatMap(Self.expansions)
                out.append(
                    Section(
                        title: "Field: \(field.labelEn)", caption: field.type.rawValue,
                        entries: accepted.isEmpty
                            ? [Entry(text: "Any \(field.type.rawValue)", isItalian: false)]
                            : accepted.map { Entry(text: $0) }))
            }
            out += Self.points(w.points ?? [], pass: w.pass)
            if let model = w.model { out.append(Section(title: "Model answer", entries: [Entry(text: model.text)])) }
        case .relay(let r):
            out.append(
                Section(
                    title: "Answer", caption: r.answerEn.type.rawValue,
                    entries: Self.relayAnswers(r.answerEn).map { Entry(text: $0, isItalian: false) }))
        }
        let near = p.near.flatMap(Self.nearEntries)
        if !near.isEmpty { out.append(Section(title: "Near misses", entries: near)) }
        self.init(exerciseID: p.id, sections: out)
    }

    /// The accepted answers of one pattern, the model answer first (docs/03: the first expansion).
    private static func accepted(_ pattern: PatternPayload) -> Section {
        let all = expansions(pattern)
        return Section(
            title: "Accepted answers", caption: pattern.source,
            entries: all.enumerated().map { Entry(text: $0.element, note: $0.offset == 0 ? "model answer" : nil) })
    }

    /// The pack's expansions; the authored source when it has none (a pattern made only of personal slots).
    private static func expansions(_ pattern: PatternPayload) -> [String] {
        pattern.expansions.isEmpty ? [pattern.source] : pattern.expansions
    }

    private static func nearEntries(_ near: NearPayload) -> [Entry] {
        let outcome =
            switch near.outcome {
            case .wrong: "not accepted"
            case .almost: "nearly right (accepted with a correction)"
            case .correctWithNote: "right, with a note"
            }
        let note = [outcome, near.hint].compactMap { $0 }.joined(separator: " · ")
        return expansions(near.answer).map { Entry(text: $0, note: note) }
    }

    private static func points(_ points: [ExerciseBody.Point], pass: Int?) -> [Section] {
        points.enumerated().map { n, point in
            Section(
                title: "Point \(n + 1): \(point.en)",
                caption: n == 0 ? pass.map { "Passes with \($0) of \(points.count) points" } : nil,
                entries: point.accept.flatMap(expansions).map { Entry(text: $0) })
        }
    }

    private static func relayAnswers(_ a: ExerciseBody.RelayAnswer) -> [String] {
        if let accept = a.accept, !accept.isEmpty { return accept }
        switch a.value {
        case .number(let d)?:
            return [a.type == .price ? String(format: "%.2f", d) : String(Int(d.rounded()))]
        case .string(let s)?:
            return [s]
        case nil:
            return []
        }
    }
}
