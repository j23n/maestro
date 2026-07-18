// ⚠️ UNTESTED SCAFFOLD.
//
// The learner-facing progress spine: can-do list grouped by level, plus
// the CEFR estimate and grammar labels. All data from one
// progress_summary call.

import SwiftUI

struct ProgressScreen: View {
    let bridge: CoreBridge
    @State private var progress: Progress?

    var body: some View {
        NavigationStack {
            List {
                if let progress {
                    Section {
                        LabeledContent("CEFR estimate", value: progress.cefrEstimate)
                        LabeledContent("Phase", value: "\(progress.currentPhase)")
                    }
                    Section("Can-do") {
                        ForEach(progress.canDos.sorted(by: { $0.key < $1.key }), id: \.key) {
                            id, state in
                            HStack {
                                statusIcon(state.status)
                                VStack(alignment: .leading) {
                                    Text(id).font(.callout)
                                    Text(
                                        "grammar \(state.grammarMastered)/\(state.grammarTotal)"
                                            + " · functions \(state.functionsDemonstrated)/\(state.functionsTotal)"
                                    )
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    Section("Grammar") {
                        ForEach(
                            progress.grammar.sorted(by: { $0.key < $1.key }), id: \.key
                        ) { id, state in
                            LabeledContent(id, value: state.label)
                        }
                    }
                }
            }
            .navigationTitle("Progress")
            .task { progress = try? bridge.progress() }
            .refreshable { progress = try? bridge.progress() }
        }
    }

    private func statusIcon(_ status: String) -> some View {
        Image(
            systemName: status == "achieved"
                ? "checkmark.seal.fill"
                : status == "in_progress" ? "circle.dotted" : "lock")
        .foregroundStyle(status == "achieved" ? .green : .secondary)
    }
}
