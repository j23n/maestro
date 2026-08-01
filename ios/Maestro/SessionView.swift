// ⚠️ UNTESTED SCAFFOLD.
//
// Plays a SessionPlan: one activity at a time, deterministic scoring via
// the core, pre-authored feedback on misses, evidence event per attempt.

import SwiftUI

struct SessionView: View {
    let bridge: CoreBridge
    let feedback: FeedbackService
    /// The learner's rough level, for prompts that adapt to it.
    let level: String
    let plan: SessionPlan
    @State private var index = 0
    @State private var correct = 0
    @State private var scored = 0
    @State private var flagging: FlagTarget?

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
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.mCream)
        // The web app puts a segment per activity above every card; a
        // counter in the title bar can't show how much is left.
        .safeAreaInset(edge: .top) {
            if index < plan.activities.count {
                LessonProgressBar(
                    total: plan.activities.count, current: index,
                    grammarIndices: grammarIndices
                )
                .padding(.horizontal, 20)
                .padding(.bottom, 10)
                .background(Color.mCream)
            }
        }
        .navigationTitle(plan.archetype.replacingOccurrences(of: "_", with: " ").capitalized)
        .navigationBarTitleDisplayMode(.inline)
        // A session is one task; the tab bar invites leaving it half-done.
        .toolbar(.hidden, for: .tabBar)
        .toolbar {
            if index < plan.activities.count {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        flagging = FlagTarget(id: plan.activities[index].itemId)
                    } label: {
                        Label("Report a problem", systemImage: "exclamationmark.bubble")
                    }
                }
            }
        }
        .sheet(item: $flagging) { target in
            FlagSheet(bridge: bridge, itemId: target.id)
        }
    }

    /// Teaching steps are drawn differently in the progress bar — they are
    /// the parts of a session the learner can't get wrong.
    private var grammarIndices: Set<Int> {
        Set(plan.activities.indices.filter { plan.activities[$0].itemType == "grammar_ref" })
    }

    @ViewBuilder
    private func activityView(_ activity: PlannedActivity) -> some View {
        switch activity.itemType {
        case "grammar_ref":
            GrammarCardView(bridge: bridge, activity: activity, onDone: advance)
        case "vocab_card":
            VocabCardView(bridge: bridge, activity: activity, onDone: advance)
        case "reading", "listening":
            PassageView(
                bridge: bridge, feedback: feedback, level: level,
                activity: activity, onDone: advance)
        case "speaking_prompt":
            SpeakingActivityView(
                bridge: bridge, feedback: feedback, level: level,
                activity: activity, onDone: advance)
        case "writing_prompt":
            WritingActivityView(
                bridge: bridge, feedback: feedback, activity: activity,
                level: level, onDone: advance)
        default:
            DrillView(
                bridge: bridge, feedback: feedback, level: level,
                activity: activity, onScored: tally, onDone: advance)
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
    let feedback: FeedbackService
    let level: String
    let activity: PlannedActivity
    var onScored: ((Bool) -> Void)? = nil
    let onDone: () -> Void

    @State private var payload: DrillPayload?
    @State private var rawEvidence: [[String: Any]] = []
    @State private var answer = ""
    @State private var result: ScoreResult?
    @State private var loadError: String?
    @State private var flagging: FlagTarget?
    @State private var explained = false

    var body: some View {
        ScrollView {
            if let loadError {
                ActivityErrorView(itemId: activity.itemId, message: loadError, onSkip: onDone)
                    .card()
                    .padding(20)
            } else {
                VStack(alignment: .leading, spacing: 16) {
                    if !activity.slot.isEmpty {
                        Badge(text: activity.slot.replacingOccurrences(of: "_", with: " "))
                    }
                    Text(payload?.prompt ?? "…")
                        .font(.title3)
                        .foregroundStyle(Color.mCharcoal)
                        .fixedSize(horizontal: false, vertical: true)

                    if let choices = payload?.choices {
                        VStack(spacing: 8) {
                            ForEach(choices, id: \.self) { choice in
                                Button {
                                    answer = choice
                                    submit(choice)
                                } label: {
                                    Text(choice).frame(maxWidth: .infinity, alignment: .leading)
                                }
                                .buttonStyle(.bordered)
                                .controlSize(.large)
                                .tint(choiceTint(choice))
                                .disabled(result != nil)
                            }
                        }
                    } else {
                        TextField("Risposta…", text: $answer)
                            .textFieldStyle(.roundedBorder)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .onSubmit { submit(answer) }
                            .disabled(result != nil)

                        // Return submits, but the web app has always shown an
                        // explicit control and there's nothing on screen to
                        // say the keyboard is the only way through.
                        if result == nil {
                            Button { submit(answer) } label: {
                                Text("Controlla").frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.large)
                            .disabled(answer.trimmingCharacters(in: .whitespaces).isEmpty)
                        }
                    }

                    if let result {
                        FeedbackView(result: result)
                        if !result.correct {
                            // The pre-authored explanation is what they were owed
                            // and already saw. This asks for a different angle —
                            // and only appears once, so it reads as an offer
                            // rather than an admission the first one was bad.
                            if !explained {
                                Button("Explain differently") { explainDifferently(result) }
                                    .font(.footnote)
                            } else {
                                FeedbackPanel(feedback: feedback)
                            }
                            // The most useful moment to ask: they have just been
                            // told they're wrong and may well disagree.
                            Button("I think my answer was right") {
                                flagging = FlagTarget(
                                    id: activity.itemId,
                                    seed: answer.isEmpty
                                        ? "" : "I answered «\(answer)» and think it should count.")
                            }
                            .font(.footnote)
                        }
                        Button { onDone() } label: {
                            Text("Continua").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                    }
                }
                .card()
                .padding(20)
            }
        }
        .task { load() }
        .sheet(item: $flagging) { target in
            // Seeded with what they typed, so the report is specific
            // without them having to retype it.
            FlagSheet(bridge: bridge, itemId: target.id, seed: target.seed)
        }
    }

    /// After scoring, the choices themselves carry the verdict — sage for
    /// the answer that was right, terracotta for the one that was picked
    /// instead (the web app's `.btn-correct` / `.btn-incorrect`).
    private func choiceTint(_ choice: String) -> Color {
        guard let result else { return .mTextMuted }
        if result.expected.contains(choice) { return .mSage }
        if choice == answer { return .mTerracotta }
        return .mTextMuted
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

    private func explainDifferently(_ result: ScoreResult) {
        explained = true
        Task {
            await feedback.request(
                kind: "mistake_explanation",
                itemId: activity.itemId,
                submission: answer,
                variables: [
                    "level": level,
                    "prompt": payload?.prompt ?? "",
                    "submission": answer,
                    "correct_answer": result.expected.joined(separator: " / "),
                    "response": answer,
                    "grammar_label": activity.slot,
                    "standard_explanation": result.feedback ?? "",
                    "weakness_tags": "",
                ])
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
                .foregroundStyle(Color.mError)
            Text(itemId).font(.caption.monospaced()).foregroundStyle(Color.mTextMuted)
            Text(message).font(.caption).foregroundStyle(Color.mTextMuted)
            Button { onSkip() } label: {
                Text("Skip").frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
    }
}

struct FeedbackView: View {
    let result: ScoreResult

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if result.correct {
                Label("Giusto!", systemImage: "checkmark.circle.fill")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(Color.mSuccess)
            } else {
                Label(
                    result.expected.joined(separator: " / "),
                    systemImage: "xmark.circle.fill"
                )
                .font(.callout.weight(.semibold))
                .foregroundStyle(Color.mError)
                if let feedback = result.feedback {
                    Text(feedback)
                        .font(.footnote)
                        .foregroundStyle(Color.mText)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            result.correct ? Color.mSuccessBg : Color.mErrorBg,
            in: RoundedRectangle(cornerRadius: 8))
    }
}

struct PassageView: View {
    let bridge: CoreBridge
    let feedback: FeedbackService
    let level: String
    let activity: PlannedActivity
    let onDone: () -> Void

    @State private var payload: ReadingPayload?
    @State private var questionIndex = -1  // -1: showing the passage

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let payload {
                if questionIndex < 0 {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 14) {
                            Eyebrow(text: activity.itemType == "listening" ? "Listening" : "Reading")
                            Text(payload.title)
                                .font(.title3.weight(.semibold))
                                .fontDesign(.serif)
                                .foregroundStyle(Color.mCharcoal)
                            if let text = payload.text {
                                Text(text)
                                    .font(.callout)
                                    .foregroundStyle(Color.mText)
                                    .lineSpacing(4)
                                    .fixedSize(horizontal: false, vertical: true)
                            } else if let turns = payload.turns {
                                ForEach(turns.indices, id: \.self) { i in
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(turns[i].speaker)
                                            .font(.caption.weight(.semibold))
                                            .foregroundStyle(Color.mBlue)
                                        Text(turns[i].text)
                                            .font(.callout)
                                            .foregroundStyle(Color.mText)
                                            .fixedSize(horizontal: false, vertical: true)
                                    }
                                }
                                // TODO(on-Mac): play pack audio; fall back to
                                // AVSpeechSynthesizer per turn when audio == nil.
                            }
                        }
                        .card()
                        .padding(20)
                    }
                    Button { questionIndex = 0 } label: {
                        Text("Alle domande →").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 8)
                } else if questionIndex < payload.questionIds.count {
                    DrillView(
                        bridge: bridge,
                        feedback: feedback,
                        level: level,
                        activity: PlannedActivity(
                            itemId: payload.questionIds[questionIndex],
                            itemType: "question", slot: activity.slot),
                        onDone: { questionIndex += 1 })
                } else {
                    Button { onDone() } label: {
                        Text("Continua").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .padding(20)
                }
            }
        }
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
        VStack(spacing: 18) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 44))
                .foregroundStyle(Color.mSage)
            Text("Sessione completata")
                .font(.title2.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(Color.mCharcoal)
            if scored > 0 {
                Text("\(correct)/\(scored) corrette")
                    .font(.headline)
                    .foregroundStyle(Color.mText)
            }
            if !plan.targetGrammar.isEmpty {
                Text(plan.targetGrammar.joined(separator: " · "))
                    .font(.caption).foregroundStyle(Color.mTextMuted)
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
                .font(.caption).foregroundStyle(Color.mTextMuted)
                .multilineTextAlignment(.center).padding(.horizontal)
            }
            Text("Progress updates on the Progress tab.")
                .font(.caption).foregroundStyle(Color.mTextMuted)
        }
        .frame(maxWidth: .infinity)
        .card(padding: 28)
        .padding(20)
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
                    VStack(alignment: .leading, spacing: 14) {
                        Eyebrow(text: "Grammar")
                        Text(payload.title)
                            .font(.title2.weight(.semibold))
                            .fontDesign(.serif)
                            .foregroundStyle(Color.mCharcoal)
                        MarkdownBody(markdown: payload.bodyMd)
                        if !payload.examples.isEmpty {
                            VStack(alignment: .leading, spacing: 8) {
                                ForEach(payload.examples, id: \.self) { example in
                                    HStack(alignment: .top, spacing: 10) {
                                        Rectangle()
                                            .fill(Color.mGold)
                                            .frame(width: 2)
                                        Text(example)
                                            .font(.callout)
                                            .italic()
                                            .foregroundStyle(Color.mText)
                                    }
                                    .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                            .padding(.top, 4)
                        }
                    }
                    .card()
                    .padding(20)
                }
                Button { markIntroduced() } label: {
                    Text("Ho capito").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .padding(.horizontal, 20)
                .padding(.bottom, 8)
            } else {
                ProgressView()
            }
        }
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
                VStack(spacing: 14) {
                    Eyebrow(text: "Vocabulary")
                    Text(payload.front)
                        .font(.system(.largeTitle, design: .serif).weight(.semibold))
                        .foregroundStyle(Color.mCharcoal)
                        .multilineTextAlignment(.center)

                    if revealed {
                        Divider().padding(.vertical, 4)
                        Text(payload.back)
                            .font(.title3.weight(.semibold))
                            .foregroundStyle(Color.mText)
                            .multilineTextAlignment(.center)
                        if let example = payload.example {
                            Text(example)
                                .font(.callout)
                                .italic()
                                .foregroundStyle(Color.mText)
                                .multilineTextAlignment(.center)
                        }
                        if let gloss = payload.exampleGloss {
                            Text(gloss)
                                .font(.footnote)
                                .foregroundStyle(Color.mTextMuted)
                                .multilineTextAlignment(.center)
                        }
                    }
                }
                .frame(maxWidth: .infinity)
                .card(padding: 28)

                Spacer()
                if revealed {
                    VStack(spacing: 8) {
                        Eyebrow(text: "How well did you know it?")
                        HStack(spacing: 8) {
                            Button("Di nuovo") { grade(1) }
                                .buttonStyle(.bordered).tint(.mTerracotta)
                            Button("Difficile") { grade(3) }
                                .buttonStyle(.bordered).tint(.mGold)
                            Button("Facile") { grade(5) }
                                .buttonStyle(.bordered).tint(.mSage)
                        }
                        .controlSize(.large)
                    }
                } else {
                    Button { revealed = true } label: {
                        Text("Mostra").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                }
            } else {
                ProgressView()
            }
        }
        .padding(20)
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
    let feedback: FeedbackService
    let level: String
    let activity: PlannedActivity
    let onDone: () -> Void

    @State private var payload: SpeakingPayload?
    @State private var loadError: String?

    var body: some View {
        VStack(spacing: 16) {
            if let loadError {
                ActivityErrorView(itemId: activity.itemId, message: loadError, onSkip: onDone)
            } else if let payload {
                VStack(alignment: .leading, spacing: 8) {
                    Eyebrow(text: "Speaking")
                    Text(payload.prompt)
                        .font(.callout)
                        .foregroundStyle(Color.mText)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                SpeakingPracticeView(
                    bridge: bridge,
                    itemId: activity.itemId,
                    target: payload.targetText,
                    evidenceJson: bridge.evidence(for: activity.itemId),
                    feedback: feedback,
                    prompt: payload.prompt,
                    level: level)
                Button { onDone() } label: {
                    Text("Continua").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            } else {
                ProgressView()
            }
        }
        .padding(20)
        .task {
            do { payload = try bridge.itemPayload(SpeakingPayload.self, id: activity.itemId) }
            catch { loadError = "\(error)" }
        }
    }
}
