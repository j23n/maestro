import SwiftUI
import ItalianCore
import PackKit
import PracticeKit

/// After the last drill: how each one went, and the topics the learner needed help with, each with
/// a Remember button for a Grammar card in the drill's sentence. No score.
struct PracticeSummaryView: View {
    let text: ReadingText
    let drills: [Drill]
    let outcomes: [String: Outcome]
    let again: () -> Void

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let keep = PracticeSummary.keepSuggestions(drills, outcomes: outcomes)
        List {
            Section {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Practice done").font(.system(size: 26, weight: .bold))
                    Text(lead(keep: keep)).foregroundStyle(.secondary)
                }
                .padding(.vertical, 6)
                .accessibilityIdentifier("practice.summary")
            }
            LabeledSection("Drills") {
                ForEach(Array(drills.enumerated()), id: \.element.id) { n, drill in
                    HStack(spacing: 10) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("\(n + 1). \(model.grammarTitle(drill.topic))").font(.subheadline)
                            if let sentence = text.sentence(drill.sentence) {
                                Text(italian: sentence.text)
                                    .font(.system(.footnote, design: .serif))
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                            }
                        }
                        Spacer(minLength: 8)
                        OutcomePill(outcome: outcomes[drill.id])
                    }
                }
            }
            if !keep.isEmpty {
                LabeledSection("Keep in Remember") {
                    ForEach(keep) { suggestion in
                        keepRow(suggestion)
                    }
                }
            }
            Section {
                Button("Back to the text") { dismiss() }
                    .buttonStyle(PrimaryButtonStyle())
                    .accessibilityIdentifier("practice.done")
                Button("Practise again", action: again)
                    .buttonStyle(SecondaryButtonStyle())
            }
            .listRowSeparator(.hidden)
        }
        .plainPage()
    }

    private func lead(keep: [KeepSuggestion]) -> String {
        let first = PracticeSummary.firstTries(drills, outcomes: outcomes)
        let base = "\(first) of \(drills.count) on the first try."
        return keep.isEmpty ? base : base + " Keep what you needed help with, and it comes back in Remember."
    }

    private func keepRow(_ suggestion: KeepSuggestion) -> some View {
        let drill = suggestion.drill
        let title = model.grammarTitle(suggestion.topic)
        var item = RememberItem.grammar(suggestion.topic, surface: title)
        if let sentence = text.sentence(drill.sentence) {
            item = item.inSentence(textID: text.id, sentenceID: sentence.id, text: sentence.text,
                                   translation: sentence.translation, ranges: drill.r.map { [$0] } ?? [])
        }
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                KindTag(kind: .grammar)
                Text(title).font(.subheadline.weight(.semibold))
                Spacer(minLength: 8)
                RememberButton(item: item, title: title)
            }
            if let sentence = text.sentence(drill.sentence) {
                Text(PracticeText.highlighted(sentence.text, range: drill.r))
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
