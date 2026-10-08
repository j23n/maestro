import Foundation
import LearningCore

/// Something the content lead can comment on (docs/04 § The review file › `target`), with what the comment sheet
/// shows: an English label and the quoted text.
struct ReviewTarget: Sendable, Hashable, Identifiable {
    /// The review file's `target`: an ID, a text line `<textId>#n` or a conversation node `<exerciseId>/<nodeId>`.
    let id: String
    let label: String
    let quote: String?
}

/// The targets of what the player shows, most specific first: the Comment button offers them in this order, and a
/// long-press on a story line or word card names one directly (docs/06 § Shared player behaviour, review mode).
enum ReviewTargets {
    static func forPage(
        _ entry: LessonPlayerModel.Entry, bundle: LessonBundle, conversationNode: String? = nil
    ) -> [ReviewTarget] {
        let step = bundle.steps[safe: entry.stepIndex]
        var out: [ReviewTarget] = []
        switch entry.page {
        case .opener(let unit):
            out.append(ReviewTarget(id: unit.rawValue, label: "The unit (title and can-dos)", quote: bundle.title))
        case .meet(let ids):
            out += ids.compactMap { bundle.items[$0] }.map(word)
        case .story(let id), .listening(let id, _), .transcript(let id), .reading(let id):
            if let text = bundle.texts[id] { out += self.text(text) }
        case .fluency(let ids, _):
            for id in ids { if let text = bundle.texts[id] { out += self.text(text) } }
        case .note(let id):
            out.append(ReviewTarget(id: id.rawValue, label: "The grammar note", quote: bundle.notes[id]?.titleEn))
        case .checkSection:
            break
        case .exercise(let id):
            if let payload = bundle.exercises[id] {
                if let node = conversationNode, case .conversation(let c) = payload.body, let n = c.node(node) {
                    out.append(
                        ReviewTarget(
                            id: "\(id.rawValue)/\(node)", label: "This turn of the conversation", quote: n.say.text))
                }
                out.append(exercise(payload))
                if let source = bundle.source(for: payload) {
                    if let n = source.line, let line = source.text.lines.first(where: { $0.number == n }) {
                        out.append(self.line(source.text, line))
                    } else {
                        out.append(textTarget(source.text))
                    }
                }
            } else {
                out.append(ReviewTarget(id: id.rawValue, label: "This exercise", quote: nil))
            }
        }
        if let step {
            out.append(ReviewTarget(id: step.id.rawValue, label: "This step (\(step.title))", quote: nil))
        }
        return out
    }

    static func exercise(_ p: ExercisePayload) -> ReviewTarget {
        ReviewTarget(id: p.id.rawValue, label: "This exercise", quote: quote(for: p))
    }

    /// A story or dialogue line, `<textId>#n` (1-based).
    static func line(_ text: PlayerText, _ line: PlayerLine) -> ReviewTarget {
        ReviewTarget(id: "\(text.id.rawValue)#\(line.number)", label: "Line \(line.number)", quote: line.text.text)
    }

    static func word(_ w: WordInfo) -> ReviewTarget {
        ReviewTarget(id: w.itemID.rawValue, label: "The word \(w.display)", quote: w.display)
    }

    /// The whole text, then each numbered line (real-world layouts have no numbered lines, docs/03).
    static func text(_ text: PlayerText) -> [ReviewTarget] {
        [textTarget(text)] + (text.layout == nil ? text.lines.map { line(text, $0) } : [])
    }

    private static func textTarget(_ text: PlayerText) -> ReviewTarget {
        ReviewTarget(
            id: text.id.rawValue, label: "The whole text", quote: text.title ?? text.lines.first?.text.text)
    }

    /// What the learner reads for an exercise: the comment's `quote`.
    static func quote(for p: ExercisePayload) -> String? {
        switch p.body {
        case .cloze(let c): return c.before.text + "___" + c.after.text
        case .recall(let r): return r.promptEn
        case .sentenceBuilding(let s): return s.promptEn
        case .dictation(let d): return d.say.text
        case .soundPair(let s):
            if let pair = s.pair { return pair.map(\.it).joined(separator: " / ") }
            return s.word?.it
        case .repeat(let r): return r.say.text
        case .choice(let c): return c.promptIt?.text ?? c.questionEn
        case .trueFalse(let t): return t.statementEn
        case .match(let m): return m.pairs.map { "\($0.left.text) = \($0.right)" }.joined(separator: "; ")
        case .conversation(let c): return c.titleEn
        case .talk(let t): return t.promptEn
        case .writing(let w): return w.promptEn
        case .relay(let r): return r.friendEn
        }
    }
}
