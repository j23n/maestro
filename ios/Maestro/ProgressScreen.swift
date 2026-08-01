// ⚠️ UNTESTED SCAFFOLD.
//
// The learner-facing progress spine: what the learner can *do*. Can-dos
// lead; the CEFR level is a footnote, shown with the evidence behind it
// so it reads as the rough estimate it is. All data from one
// progress_summary call.

import SwiftUI

struct ProgressScreen: View {
    let bridge: CoreBridge
    @State private var progress: Progress?

    var body: some View {
        NavigationStack {
            List {
                if let progress {
                    Section("What you can do") {
                        ForEach(progress.canDos.sorted(by: { $0.key < $1.key }), id: \.key) {
                            id, state in
                            HStack(alignment: .top, spacing: 10) {
                                statusIcon(state.status)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(state.label)
                                        .font(.callout)
                                        .foregroundStyle(Color.mText)
                                    Text(
                                        "grammar \(state.grammarMastered)/\(state.grammarTotal)"
                                            + " · functions \(state.functionsDemonstrated)/\(state.functionsTotal)"
                                    )
                                    .font(.caption)
                                    .foregroundStyle(Color.mTextMuted)
                                }
                            }
                            .padding(.vertical, 2)
                        }
                    }
                    Section("Grammar") {
                        ForEach(
                            progress.grammar.sorted(by: { $0.key < $1.key }), id: \.key
                        ) { id, state in
                            LabeledContent(state.displayName, value: state.label)
                        }
                    }
                    // Deliberately last and understated: a rough level, not
                    // an achievement. `confidence` guards against reading a
                    // thinly-evidenced estimate as a result.
                    Section {
                        LabeledContent("Roughly", value: progress.cefr.summary)
                        LabeledContent("Confidence", value: progress.cefr.confidence)
                        LabeledContent("Phase", value: "\(progress.currentPhase)")
                    } header: {
                        Text("Level estimate")
                    } footer: {
                        Text(
                            "An estimate from what you've practised so far — "
                                + "your can-dos above are the real measure.")
                    }
                }
            }
            .safeAreaInset(edge: .bottom) {
                NavigationLink {
                    ReportedProblemsView(bridge: bridge)
                } label: {
                    Label("Reported problems", systemImage: "exclamationmark.bubble")
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                }
                .background(.bar)
            }
            .creamBackground()
            .navigationTitle("Progress")
            .task { progress = try? bridge.progress() }
            .refreshable { progress = try? bridge.progress() }
        }
    }

    private func statusIcon(_ status: String) -> some View {
        Image(
            systemName: status == "achieved"
                ? "checkmark.seal.fill"
                : status == "in_progress" ? "circle.dotted" : "lock"
        )
        .foregroundStyle(
            status == "achieved"
                ? Color.mSage : status == "in_progress" ? Color.mGold : Color.mTextMuted)
    }
}
