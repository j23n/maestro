// ⚠️ UNTESTED SCAFFOLD.
//
// Plays a SessionPlan: one activity at a time, deterministic scoring via
// the core, pre-authored feedback on misses, evidence event per attempt.

import SwiftUI

struct SessionView: View {
    let bridge: CoreBridge
    let plan: SessionPlan
    @State private var index = 0
    @State private var correct = 0
    @State private var scored = 0

    var body: some View {
        Group {
            if index < plan.activities.count {
                activityView(plan.activities[index])
                    .id(plan.activities[index].itemId)
            } else {
                SessionSummaryView(
                    plan: plan, correct: correct, scored: scored,
                    onAppear: recordCompletion)
            }
        }
        .navigationTitle("\(min(index + 1, plan.activities.count))/\(plan.activities.count) · \(plan.archetype)")
    }

    @ViewBuilder
    private func activityView(_ activity: PlannedActivity) -> some View {
        switch activity.itemType {
        case "grammar_ref":
            GrammarCardView(bridge: bridge, activity: activity, onDone: advance)
        case "vocab_card":
            VocabCardView(bridge: bridge, activity: activity, onDone: advance)
        case "reading", "listening":
            PassageView(bridge: bridge, activity: activity, onDone: advance)
        case "speaking_prompt":
            SpeakingActivityView(bridge: bridge, activity: activity, onDone: advance)
        default:
            DrillView(bridge: bridge, activity: activity, onScored: tally, onDone: advance)
        }
    }

    private func advance() { index += 1 }

    private func tally(_ wasCorrect: Bool) {
        scored += 1
        if wasCorrect { correct += 1 }
    }

    /// The composer orders scenarios by completion count, so this event is
    /// what unlocks the next lesson. Without it the learner replays lesson
    /// one forever (core/tests/five_lessons.rs pins exactly that).
    private func recordCompletion() {
        guard let scenarioId = plan.scenarioId else { return }
        try? bridge.recordScenarioCompleted(scenarioId: scenarioId)
    }
}

struct DrillView: View {
    let bridge: CoreBridge
    let activity: PlannedActivity
    var onScored: ((Bool) -> Void)? = nil
    let onDone: () -> Void

    @State private var payload: DrillPayload?
    @State private var rawEvidence: [[String: Any]] = []
    @State private var answer = ""
    @State private var result: ScoreResult?
    @State private var loadError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let loadError {
                ActivityErrorView(itemId: activity.itemId, message: loadError, onSkip: onDone)
            } else {
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
            }
            Spacer()
        }
        .padding()
        .task { load() }
    }

    private func load() {
        do {
            payload = try bridge.itemPayload(DrillPayload.self, id: activity.itemId)
            // Evidence passes through the bridge untyped (recorded verbatim).
            rawEvidence = bridge.evidence(for: activity.itemId)
        } catch {
            loadError = "\(error)"
        }
    }

    private func submit(_ text: String) {
        do {
            let scored = try bridge.score(itemId: activity.itemId, response: text)
            result = scored
            onScored?(scored.correct)
            try bridge.recordAttempt(
                itemId: activity.itemId,
                outcome: scored.correct ? "correct" : "incorrect",
                modality: "writing",
                evidenceClass: "targeted",
                evidenceJson: rawEvidence,
                response: text)
        } catch {
            loadError = "\(error)"
        }
    }
}

/// An activity that can't be shown is a bug worth seeing, not a blank
/// screen: name the item and let the learner move on.
struct ActivityErrorView: View {
    let itemId: String
    let message: String
    let onSkip: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Couldn't load this activity", systemImage: "exclamationmark.triangle")
                .font(.headline)
            Text(itemId).font(.caption.monospaced()).foregroundStyle(.secondary)
            Text(message).font(.caption).foregroundStyle(.secondary)
            Button("Skip") { onSkip() }.buttonStyle(.borderedProminent)
        }
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
    let plan: SessionPlan
    let correct: Int
    let scored: Int
    let onAppear: () -> Void

    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 48)).foregroundStyle(.green)
            Text("Sessione completata").font(.title2)
            if scored > 0 {
                Text("\(correct)/\(scored) corrette").font(.headline)
            }
            if !plan.targetGrammar.isEmpty {
                Text(plan.targetGrammar.joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            // A short lesson means the pack ran out, not that the lesson
            // was short. Say so rather than letting it read as complete.
            if !plan.shortfalls.isEmpty {
                Label(
                    "Some activities were skipped — this lesson doesn't have "
                        + "enough content yet.",
                    systemImage: "tray"
                )
                .font(.caption).foregroundStyle(.secondary)
                .multilineTextAlignment(.center).padding(.horizontal)
            }
            Text("Progress updates on the Progress tab.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding()
        .onAppear(perform: onAppear)
    }
}

/// The teach step of an introduction session: the reference page for a
/// grammar point, ahead of the drills that assume it. Viewing it records
/// an `introduced` event, which is what stops the composer re-introducing
/// the same grammar every session.
struct GrammarCardView: View {
    let bridge: CoreBridge
    let activity: PlannedActivity
    let onDone: () -> Void

    @State private var payload: GrammarRefPayload?
    @State private var loadError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let loadError {
                ActivityErrorView(itemId: activity.itemId, message: loadError, onSkip: onDone)
            } else if let payload {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(payload.title).font(.title2.bold())
                        // LocalizedStringKey renders inline markdown (bold,
                        // italic, links) with no dependency, but NOT tables
                        // or headings — and several reference pages use
                        // tables, which will show as raw pipes until this
                        // grows a real markdown view. Cosmetic, on-Mac fix.
                        Text(LocalizedStringKey(payload.bodyMd))
                        if !payload.examples.isEmpty {
                            Divider()
                            ForEach(payload.examples, id: \.self) { example in
                                Text(example).italic()
                            }
                        }
                    }
                }
                Button("Ho capito") { markIntroduced() }
                    .buttonStyle(.borderedProminent)
            } else {
                ProgressView()
            }
        }
        .padding()
        .task {
            do { payload = try bridge.itemPayload(GrammarRefPayload.self, id: activity.itemId) }
            catch { loadError = "\(error)" }
        }
    }

    private func markIntroduced() {
        try? bridge.recordIntroduced(evidenceJson: bridge.evidence(for: activity.itemId))
        onDone()
    }
}

/// SM-2 vocab review: show the Italian, self-grade the recall. The rating
/// drives the card's next due date in the core's scheduler.
struct VocabCardView: View {
    let bridge: CoreBridge
    let activity: PlannedActivity
    let onDone: () -> Void

    @State private var payload: VocabCardPayload?
    @State private var revealed = false
    @State private var loadError: String?

    var body: some View {
        VStack(spacing: 20) {
            if let loadError {
                ActivityErrorView(itemId: activity.itemId, message: loadError, onSkip: onDone)
            } else if let payload {
                Spacer()
                Text(payload.front).font(.largeTitle)
                if revealed {
                    Text(payload.back).font(.title3).foregroundStyle(.secondary)
                    if let example = payload.example {
                        Text(example).italic().multilineTextAlignment(.center)
                    }
                    if let gloss = payload.exampleGloss {
                        Text(gloss).font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if revealed {
                    HStack(spacing: 12) {
                        Button("Di nuovo") { grade(1) }.buttonStyle(.bordered)
                        Button("Difficile") { grade(3) }.buttonStyle(.bordered)
                        Button("Facile") { grade(5) }.buttonStyle(.borderedProminent)
                    }
                } else {
                    Button("Mostra") { revealed = true }.buttonStyle(.borderedProminent)
                }
            } else {
                ProgressView()
            }
        }
        .padding()
        .task {
            do { payload = try bridge.itemPayload(VocabCardPayload.self, id: activity.itemId) }
            catch { loadError = "\(error)" }
        }
    }

    private func grade(_ rating: UInt8) {
        try? bridge.recordVocabReview(
            itemId: activity.itemId, srsRating: rating,
            evidenceJson: bridge.evidence(for: activity.itemId))
        onDone()
    }
}

/// Wraps SpeakingPracticeView with the item's own target text, so a
/// speaking_prompt activity scores against what the pack authored rather
/// than a hardcoded sentence.
struct SpeakingActivityView: View {
    let bridge: CoreBridge
    let activity: PlannedActivity
    let onDone: () -> Void

    @State private var payload: SpeakingPayload?
    @State private var loadError: String?

    var body: some View {
        VStack(spacing: 16) {
            if let loadError {
                ActivityErrorView(itemId: activity.itemId, message: loadError, onSkip: onDone)
            } else if let payload {
                Text(payload.prompt).font(.callout).foregroundStyle(.secondary)
                SpeakingPracticeView(
                    bridge: bridge,
                    itemId: activity.itemId,
                    target: payload.targetText,
                    evidenceJson: bridge.evidence(for: activity.itemId))
                Button("Continua") { onDone() }.buttonStyle(.borderedProminent)
            } else {
                ProgressView()
            }
        }
        .padding()
        .task {
            do { payload = try bridge.itemPayload(SpeakingPayload.self, id: activity.itemId) }
            catch { loadError = "\(error)" }
        }
    }
}
