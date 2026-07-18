// ⚠️ UNTESTED SCAFFOLD.
//
// Plays a SessionPlan: one activity at a time, deterministic scoring via
// the core, pre-authored feedback on misses, evidence event per attempt.

import SwiftUI

struct SessionView: View {
    let bridge: CoreBridge
    let plan: SessionPlan
    @State private var index = 0

    var body: some View {
        Group {
            if index < plan.activities.count {
                activityView(plan.activities[index])
                    .id(plan.activities[index].itemId)
            } else {
                SessionSummaryView()
            }
        }
        .navigationTitle("\(index + 1)/\(plan.activities.count) · \(plan.archetype)")
    }

    @ViewBuilder
    private func activityView(_ activity: PlannedActivity) -> some View {
        switch activity.itemType {
        case "reading", "listening":
            PassageView(bridge: bridge, activity: activity, onDone: advance)
        default:
            DrillView(bridge: bridge, activity: activity, onDone: advance)
        }
    }

    private func advance() { index += 1 }
}

struct DrillView: View {
    let bridge: CoreBridge
    let activity: PlannedActivity
    let onDone: () -> Void

    @State private var payload: DrillPayload?
    @State private var rawEvidence: [[String: Any]] = []
    @State private var answer = ""
    @State private var result: ScoreResult?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(payload?.prompt ?? "…").font(.title3)
            if let choices = payload?.choices {
                ForEach(choices, id: \.self) { choice in
                    Button(choice) { submit(choice) }
                        .buttonStyle(.bordered)
                        .disabled(result != nil)
                }
            } else {
                TextField("Risposta…", text: $answer)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .onSubmit { submit(answer) }
                    .disabled(result != nil)
            }
            if let result {
                FeedbackView(result: result)
                Button("Continua") { onDone() }.buttonStyle(.borderedProminent)
            }
            Spacer()
        }
        .padding()
        .task { load() }
    }

    private func load() {
        payload = try? bridge.itemPayload(DrillPayload.self, id: activity.itemId)
        // Evidence passes through the bridge untyped (recorded verbatim).
        if let json = try? bridge.itemPayloadRaw(id: activity.itemId),
           let obj = try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any],
           let ev = obj["evidence"] as? [[String: Any]] {
            rawEvidence = ev
        }
    }

    private func submit(_ text: String) {
        guard let scored = try? bridge.score(itemId: activity.itemId, response: text)
        else { return }
        result = scored
        try? bridge.recordAttempt(
            itemId: activity.itemId,
            outcome: scored.correct ? "correct" : "incorrect",
            modality: "writing",
            evidenceClass: "targeted",
            evidenceJson: rawEvidence,
            response: text)
    }
}

struct FeedbackView: View {
    let result: ScoreResult

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if result.correct {
                Label("Giusto!", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            } else {
                Label(result.expected.joined(separator: " / "),
                      systemImage: "xmark.circle.fill")
                    .foregroundStyle(.red)
                if let feedback = result.feedback {
                    Text(feedback).font(.callout).foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 8)
    }
}

struct PassageView: View {
    let bridge: CoreBridge
    let activity: PlannedActivity
    let onDone: () -> Void

    @State private var payload: ReadingPayload?
    @State private var questionIndex = -1  // -1: showing the passage

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let payload {
                if questionIndex < 0 {
                    ScrollView {
                        Text(payload.title).font(.headline)
                        if let text = payload.text {
                            Text(text)
                        } else if let turns = payload.turns {
                            ForEach(turns.indices, id: \.self) { i in
                                Text("\(turns[i].speaker): \(turns[i].text)")
                            }
                            // TODO(on-Mac): play pack audio; fall back to
                            // AVSpeechSynthesizer per turn when audio == nil.
                        }
                    }
                    Button("Alle domande →") { questionIndex = 0 }
                        .buttonStyle(.borderedProminent)
                } else if questionIndex < payload.questionIds.count {
                    DrillView(
                        bridge: bridge,
                        activity: PlannedActivity(
                            itemId: payload.questionIds[questionIndex],
                            itemType: "question", slot: activity.slot),
                        onDone: { questionIndex += 1 })
                } else {
                    Button("Continua") { onDone() }.buttonStyle(.borderedProminent)
                }
            }
        }
        .padding()
        .task {
            payload = try? bridge.itemPayload(ReadingPayload.self, id: activity.itemId)
        }
    }
}

struct SessionSummaryView: View {
    var body: some View {
        ContentUnavailableView(
            "Sessione completata",
            systemImage: "checkmark.seal",
            description: Text("Evidence recorded; progress updates on the Progress tab."))
    }
}
