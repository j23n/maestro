import SwiftUI
import LanguageCore
import PackKit
import PracticeKit

/// The wrap-up of a session (HANDOFF.md 3.9): what to keep in Remember, each in its sentence, how each
/// stage went, and the drills that needed help. No score.
struct SessionSummaryView: View {
    let text: ReadingText
    let stages: [SessionStage]
    let outcomes: [String: Outcome]
    let minutes: Int
    let again: () -> Void

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    private var drillStages: [SessionStage] { stages.filter { !$0.drills.isEmpty } }
    private var all: [SessionDrill] { drillStages.flatMap(\.drills) }

    var body: some View {
        let keep = keepSuggestions
        let help = neededHelp
        List {
            Section {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Session done").font(.system(size: 26, weight: .bold))
                    Text(lead(keep: keep)).foregroundStyle(.secondary)
                }
                .padding(.vertical, 6)
                .accessibilityIdentifier("practice.summary")
            }
            if !keep.isEmpty {
                LabeledSection("Keep in Remember") {
                    ForEach(keep) { entry in
                        keepRow(entry.suggestion, textID: entry.textID)
                    }
                }
            }
            if !drillStages.isEmpty {
                LabeledSection("Stages") {
                    ForEach(drillStages) { stage in
                        HStack(spacing: 10) {
                            Tag(text: stage.kind.title, colors: Theme.stage(stage.kind))
                            Spacer(minLength: 8)
                            Text("\(firstTries(stage.drills)) of \(stage.drills.count) on the first try")
                                .font(.subheadline.monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                        .frame(minHeight: 36)
                        .accessibilityElement(children: .combine)
                    }
                }
            }
            if !help.isEmpty {
                LabeledSection("Needed help") {
                    ForEach(help) { entry in
                        helpRow(entry.kind, entry.item)
                    }
                }
            }
            Section {
                Button("Done") { dismiss() }
                    .buttonStyle(PrimaryButtonStyle())
                    .accessibilityIdentifier("practice.done")
                Button("Practise again", action: again)
                    .buttonStyle(SecondaryButtonStyle())
            }
            .listRowSeparator(.hidden)
        }
        .plainPage()
    }

    private func firstTries(_ drills: [SessionDrill]) -> Int {
        drills.filter { outcomes[$0.id] == .firstTry }.count
    }

    private func lead(keep: [KeepEntry]) -> String {
        let time = minutes == 1 ? "about a minute" : "about \(minutes) minutes"
        let base: String
        if !all.isEmpty {
            base = "\(firstTries(all)) of \(all.count) on the first try, in \(time)."
        } else if stages.contains(where: { $0.kind == .questions }) {
            base = "You answered the questions, in \(time)."
        } else {
            base = "You read the text, in \(time)."
        }
        return keep.isEmpty ? base : base + " Keep what you needed help with, and it comes back in Remember."
    }

    // MARK: Needed help

    struct HelpEntry: Identifiable {
        let kind: StageKind
        let item: SessionDrill
        var id: String { item.id }
    }

    /// The session's drills that weren't right on the first try, in session order.
    private var neededHelp: [HelpEntry] {
        var out: [HelpEntry] = []
        for stage in drillStages {
            for item in stage.drills where (outcomes[item.id] ?? .shown) != .firstTry {
                out.append(HelpEntry(kind: stage.kind, item: item))
            }
        }
        return out
    }

    private func helpRow(_ kind: StageKind, _ item: SessionDrill) -> some View {
        let drillText = model.text(item.textID)
        let sentence = drillText?.sentence(item.drill.sentence)
        return HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
                Tag(text: kind.title, colors: Theme.stage(kind))
                if let sentence {
                    Text(PracticeText.highlighted(sentence.text, range: item.drill.r ?? item.drill.focus))
                        .font(.system(.footnote, design: .serif))
                        .lineLimit(2)
                } else {
                    Text(item.drill.prompt).font(.footnote).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 8)
            OutcomePill(outcome: outcomes[item.id])
        }
    }

    // MARK: Keep

    struct KeepEntry: Identifiable {
        let textID: String
        let suggestion: KeepSuggestion
        var id: String { suggestion.id }
    }

    /// The suggestions of each text in the session, this text's first, each item once.
    private var keepSuggestions: [KeepEntry] {
        var order: [String] = []
        var byText: [String: [SessionDrill]] = [:]
        for item in all {
            if byText[item.textID] == nil { order.append(item.textID) }
            byText[item.textID, default: []].append(item)
        }
        var seen: Set<String> = []
        var out: [KeepEntry] = []
        for textID in order {
            let items = byText[textID] ?? []
            var byDrill: [String: Outcome] = [:]
            for item in items { byDrill[item.drill.id] = outcomes[item.id] ?? .shown }
            let source = textID == text.id ? text : model.text(textID)
            for suggestion in PracticeSummary.keepSuggestions(items.map(\.drill), outcomes: byDrill, text: source)
            where seen.insert(suggestion.id).inserted {
                out.append(KeepEntry(textID: textID, suggestion: suggestion))
            }
        }
        return out
    }

    struct KeepItem {
        let item: RememberItem
        let title: String
        let kind: ItemKind
    }

    private func rememberItem(_ suggestion: KeepSuggestion) -> KeepItem {
        switch suggestion.item {
        case .grammar(let topic):
            let title = model.grammarTitle(topic)
            return KeepItem(item: RememberItem.grammar(topic, surface: title), title: title, kind: .grammar)
        case .word(let lemmaID, let senseID, let surface):
            return KeepItem(item: RememberItem.word(lemmaID: lemmaID, senseID: senseID, surface: surface),
                            title: surface, kind: .word)
        case .verbForm(let lemmaID, let formTag, let surface):
            return KeepItem(item: RememberItem.verbForm(lemmaID: lemmaID, formTag: formTag, surface: surface),
                            title: surface, kind: .verbForm)
        }
    }

    private func keepRow(_ suggestion: KeepSuggestion, textID: String) -> some View {
        let drill = suggestion.drill
        let entry = rememberItem(suggestion)
        let sentence = model.text(textID)?.sentence(drill.sentence)
        var item = entry.item
        if let sentence {
            item = item.inSentence(textID: textID, sentenceID: sentence.id, text: sentence.text,
                                   translation: sentence.translation, ranges: suggestion.range.map { [$0] } ?? [])
        }
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                KindTag(kind: entry.kind)
                if entry.kind == .grammar {
                    Text(entry.title).font(.subheadline.weight(.semibold))
                } else {
                    Text(target: entry.title).font(.system(.subheadline, design: .serif).weight(.semibold))
                }
                Spacer(minLength: 8)
                RememberButton(item: item, title: entry.title)
            }
            if let sentence {
                Text(PracticeText.highlighted(sentence.text, range: suggestion.range))
                    .font(.system(.body, design: .serif))
            }
        }
        .padding(.vertical, 4)
    }
}

struct OutcomePill: View {
    let outcome: Outcome?

    var body: some View {
        let colors: Theme.Pair = switch outcome {
        case .firstTry: Theme.added
        case .afterHint: Theme.warning
        case .shown, nil: Theme.error
        }
        Text(outcome?.label ?? "Skipped")
            .font(.caption.weight(.semibold))
            .lineLimit(1)
            .fixedSize()
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .foregroundStyle(colors.foreground)
            .background(colors.background, in: Capsule())
    }
}
