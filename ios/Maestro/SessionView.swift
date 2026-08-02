// ⚠️ UNTESTED SCAFFOLD.
//
// Plays a SessionPlan: one activity at a time, deterministic scoring via
// the core, pre-authored feedback on misses, evidence event per attempt.

import AVFoundation
import SwiftUI
import UIKit

/// What actually happened in a session, gathered as it plays.
///
/// Kept here rather than re-derived from the event log afterwards: the log
/// is keyed by evidence axis and has no notion of "this lesson", so the
/// session is the only thing that knows what one session contained.
@Observable
final class SessionTally {
    struct Miss: Identifiable {
        let itemId: String
        let prompt: String
        let answer: String
        let expected: String
        var id: String { itemId }
    }

    private(set) var scored = 0
    private(set) var correct = 0
    private(set) var misses: [Miss] = []
    /// Lemmas this session was the learner's first meeting with.
    private(set) var newWords: [String] = []
    private var knownWords: Set<String>

    init(knownWords: Set<String> = []) {
        self.knownWords = knownWords
    }

    func record(
        correct wasCorrect: Bool, itemId: String, prompt: String, answer: String,
        expected: String
    ) {
        scored += 1
        if wasCorrect {
            correct += 1
        } else {
            misses.append(
                Miss(itemId: itemId, prompt: prompt, answer: answer, expected: expected))
        }
    }

    func met(_ lemmas: [String]) {
        for lemma in lemmas where knownWords.insert(lemma).inserted {
            newWords.append(lemma)
        }
    }
}

struct SessionView: View {
    let bridge: CoreBridge
    let feedback: FeedbackService
    /// The learner's rough level, for prompts that adapt to it.
    let level: String
    let plan: SessionPlan
    /// Compose and push another lesson from the recap.
    var onNextLesson: (() -> Void)?
    @State private var index = 0
    @State private var tally = SessionTally()
    @State private var primed = false
    @State private var flagging: FlagTarget?
    @State private var brief: LessonBrief?

    var body: some View {
        Group {
            if index < plan.activities.count {
                activityView(plan.activities[index])
                    .id(plan.activities[index].itemId)
            } else {
                SessionRecapView(
                    bridge: bridge, plan: plan, tally: tally,
                    onNextLesson: onNextLesson, onAppear: recordCompletion)
            }
        }
        // One task, so the vocabulary snapshot is always taken before the
        // first activity's words are checked against it.
        .task(id: index) {
            if !primed {
                primed = true
                let known = (try? bridge.vocabulary()) ?? []
                tally = SessionTally(
                    knownWords: Set(known.filter { $0.status != "new" }.map(\.lemma)))
                if let id = plan.scenarioId { brief = try? bridge.lesson(scenarioId: id) }
            }
            noteWords()
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
        // The lesson's name, not the composer's word for its shape.
        // "Consolidation" and "First Visit" are how the machine picks a
        // slot layout; the learner is at the bar.
        .navigationTitle(title)
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

    /// The lesson's own name, resolved once the brief loads. A practice
    /// run has no lesson to name, so it says what it is.
    private var title: String {
        if plan.practice { return "Esercizi" }
        return brief?.label ?? "Lezione"
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
                activity: activity, tally: tally, onDone: advance)
        case "speaking_prompt":
            SpeakingActivityView(
                bridge: bridge, feedback: feedback, level: level,
                activity: activity, onDone: advance)
        case "task":
            CapstoneView(
                bridge: bridge, feedback: feedback, level: level,
                activity: activity, onDone: advance)
        case "writing_prompt":
            WritingActivityView(
                bridge: bridge, feedback: feedback, activity: activity,
                level: level, onDone: advance)
        default:
            DrillView(
                bridge: bridge, feedback: feedback, level: level,
                activity: activity, tally: tally, onDone: advance)
        }
    }

    private func advance() { index += 1 }

    /// Add the current activity's vocabulary to the learner's, and note
    /// which of it they had never met.
    private func noteWords() {
        guard index < plan.activities.count else { return }
        let itemId = plan.activities[index].itemId
        tally.met(bridge.vocabIds(for: itemId))
        try? bridge.recordEncountered(
            itemId: itemId, evidenceJson: bridge.evidence(for: itemId))
    }

    /// The composer orders scenarios by completion count, so this event is
    /// what unlocks the next lesson. Without it the learner replays lesson
    /// one forever (core/tests/five_lessons.rs pins exactly that).
    ///
    /// The depth matters as much as the id: `max_depth_completed` is what
    /// decides whether a scenario is finished or has framings left, so
    /// reporting every session as depth 1 makes a one-depth scenario
    /// retire after a single visit and a three-depth one never move past
    /// its first.
    private func recordCompletion() {
        // Practice runs over material already met complete nothing. A new
        // learner's first tap on "quick drills" used to retire "In aereo"
        // — the opening scene — without ever showing it to them.
        guard let scenarioId = plan.scenarioId, !plan.practice else { return }
        try? bridge.recordScenarioCompleted(scenarioId: scenarioId, depth: plan.depth)
    }
}

struct DrillView: View {
    let bridge: CoreBridge
    let feedback: FeedbackService
    let level: String
    let activity: PlannedActivity
    var tally: SessionTally? = nil
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
                    if let label = SlotLabel.of(activity.slot) {
                        Badge(text: label)
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
            tally?.record(
                correct: scored.correct, itemId: activity.itemId,
                prompt: payload?.prompt ?? "", answer: text,
                expected: scored.expected.joined(separator: " / "))
            // No evidenceClass: the item's authored rung decides. A drill
            // is targeted production, a comprehension question routed
            // through this same view is not, and only the pack knows.
            try bridge.recordAttempt(
                itemId: activity.itemId,
                outcome: scored.correct ? "correct" : "incorrect",
                modality: "writing",
                evidenceJson: rawEvidence,
                response: text)
        } catch {
            loadError = "\(error)"
        }
    }
}

/// The lesson's last beat: the task that proves a can-do.
///
/// Framed as a performance rather than another exercise — the goal is
/// stated, the success criteria are visible, and at the `perform` rung
/// there is no model answer on screen to lean on. It routes to the two
/// scorers that already exist rather than inventing a third.
struct CapstoneView: View {
    let bridge: CoreBridge
    let feedback: FeedbackService
    let level: String
    let activity: PlannedActivity
    let onDone: () -> Void

    @State private var payload: TaskPayload?
    @State private var loadError: String?

    var body: some View {
        VStack(spacing: 16) {
            if let loadError {
                ActivityErrorView(itemId: activity.itemId, message: loadError, onSkip: onDone)
            } else if let payload {
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        Eyebrow(text: "Prova finale")
                        Text(payload.prompt)
                            .font(.title3)
                            .foregroundStyle(Color.mCharcoal)
                            .fixedSize(horizontal: false, vertical: true)
                        if !payload.rubric.isEmpty {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Per riuscire")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(Color.mTextMuted)
                                ForEach(payload.rubric, id: \.self) { line in
                                    HStack(alignment: .top, spacing: 8) {
                                        Image(systemName: "checkmark")
                                            .font(.caption2)
                                            .foregroundStyle(Color.mSage)
                                            .padding(.top, 3)
                                        Text(line)
                                            .font(.footnote)
                                            .foregroundStyle(Color.mText)
                                    }
                                }
                            }
                        }
                        if payload.mode == "speaking" {
                            SpeakingPracticeView(
                                bridge: bridge,
                                itemId: activity.itemId,
                                // nil at `perform`: nothing to read off.
                                target: payload.targetText ?? "",
                                evidenceJson: bridge.evidence(for: activity.itemId),
                                feedback: feedback,
                                prompt: payload.prompt,
                                level: level)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .card()
                    .padding(20)
                }
                if payload.mode == "writing" {
                    WritingActivityView(
                        bridge: bridge, feedback: feedback, activity: activity,
                        level: level, onDone: onDone)
                } else {
                    Button { onDone() } label: {
                        Text("Continua").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 8)
                }
            } else {
                ProgressView()
            }
        }
        .task {
            do { payload = try bridge.itemPayload(TaskPayload.self, id: activity.itemId) }
            catch { loadError = "\(error)" }
        }
    }
}

/// What a slot is called to the learner, where it's worth saying at all.
///
/// Slot names are the composer's vocabulary: `weakness_drill` says the
/// app has decided you're bad at something, `new_grammar_drill` says
/// nothing you can't see for yourself. Only the two that change what the
/// learner should expect get a badge — a revisit is deliberately
/// something they've met before, and a capstone is the thing the lesson
/// was for.
enum SlotLabel {
    static func of(_ slot: String) -> String? {
        switch slot {
        case "revisit": return "Ripasso"
        case "capstone": return "Prova finale"
        default: return nil
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
    var tally: SessionTally? = nil
    let onDone: () -> Void

    @State private var payload: ReadingPayload?
    @State private var questionIndex = -1  // -1: showing the passage
    @State private var speaker = DialogueSpeaker()
    /// Listening hides its transcript until asked. Reading is always shown.
    @State private var transcriptShown = false

    private var isListening: Bool { activity.itemType == "listening" }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let payload {
                if questionIndex < 0 {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 14) {
                            Eyebrow(text: isListening ? "Listening" : "Reading")
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
                                // The pack ships no audio yet, so the device
                                // voice reads the dialogue. Without this a
                                // listening activity is just a reading with a
                                // different label.
                                Button {
                                    speaker.isSpeaking
                                        ? speaker.stop() : speaker.speak(turns)
                                } label: {
                                    Label(
                                        speaker.isSpeaking ? "Ferma" : "Ascolta",
                                        systemImage: speaker.isSpeaking
                                            ? "stop.fill" : "play.fill")
                                }
                                .buttonStyle(.bordered)
                                .controlSize(.large)

                                if transcriptShown {
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
                                } else {
                                    Button("Mostra il testo") { transcriptShown = true }
                                        .font(.footnote)
                                }
                                if let note = speaker.unavailable {
                                    Text(note)
                                        .font(.caption)
                                        .foregroundStyle(Color.mTextMuted)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                        }
                        // A listening card holds a button and a link, not a
                        // passage; without this it shrinks to their width.
                        .frame(maxWidth: .infinity, alignment: .leading)
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
                        tally: tally,
                        // The last question's Continua leaves the passage
                        // outright; a second one on an empty screen is a tap
                        // that does nothing but confirm the first.
                        onDone: {
                            questionIndex += 1
                            if questionIndex >= payload.questionIds.count { onDone() }
                        })
                        // Without this the drill keeps its identity across
                        // questions, so its @State — payload, answer, verdict —
                        // survives and every question after the first renders
                        // as the previous one, already answered.
                        .id(payload.questionIds[questionIndex])
                }
            }
        }
        .task {
            payload = try? bridge.itemPayload(ReadingPayload.self, id: activity.itemId)
            transcriptShown = !isListening
        }
        .onDisappear { speaker.stop() }
    }
}

/// Reads a dialogue aloud in Italian, one turn after another.
///
/// A stand-in for pack audio, not a replacement: when the pack ships
/// recorded turns this gives way to them. It exists because a listening
/// activity with nothing to listen to isn't one.
@Observable
final class DialogueSpeaker: NSObject, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private(set) var isSpeaking = false
    /// Set when the device has no Italian voice to read with. Silence with
    /// a play button that does nothing looks like a broken app; saying so
    /// at least tells the learner where to go.
    private(set) var unavailable: String?

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    /// The best Italian voice installed, whatever its region tag. Voice
    /// assets are downloaded on demand, so "it-IT" specifically is not
    /// guaranteed to exist even when Italian speech does.
    private static var italianVoice: AVSpeechSynthesisVoice? {
        AVSpeechSynthesisVoice(language: "it-IT")
            ?? AVSpeechSynthesisVoice.speechVoices()
                .first { $0.language.hasPrefix("it") }
    }

    func speak(_ turns: [DialogueTurn]) {
        stop()
        guard let voice = Self.italianVoice else {
            unavailable =
                "No Italian voice is installed on this device. Add one in "
                + "Settings › Accessibility › Spoken Content › Voices."
            return
        }
        unavailable = nil
        // Speech shares the audio session with recording elsewhere in the
        // app, and without an explicit playback category it is silenced by
        // the ring/silent switch — which reads as the feature not working.
        try? AVAudioSession.sharedInstance().setCategory(
            .playback, mode: .spokenAudio, options: [.duckOthers])
        try? AVAudioSession.sharedInstance().setActive(true)

        isSpeaking = true
        for turn in turns {
            let utterance = AVSpeechUtterance(string: turn.text)
            utterance.voice = voice
            // Slower than conversational: this is comprehension practice
            // for a beginner, not a native-speed listening test.
            utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.85
            utterance.postUtteranceDelay = 0.4
            synthesizer.speak(utterance)
        }
    }

    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
        isSpeaking = false
    }

    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer, didStart utterance: AVSpeechUtterance
    ) {
        isSpeaking = true
    }

    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance
    ) {
        // Turns are queued together, so the last one finishing ends the run.
        if !synthesizer.isSpeaking { isSpeaking = false }
    }

    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance
    ) {
        isSpeaking = false
    }
}

/// What the lesson covered, what went wrong, and the way on to the next
/// one. The old summary showed a score and a row of grammar ids; the point
/// of a recap is that the learner can see what they just did.
struct SessionRecapView: View {
    let bridge: CoreBridge
    let plan: SessionPlan
    let tally: SessionTally
    var onNextLesson: (() -> Void)?
    let onAppear: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var brief: LessonBrief?
    @State private var words: [VocabEntry] = []

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                if tally.scored > 0 { scoreCard }
                coveredCard
                if !newWords.isEmpty { wordsCard }
                if !tally.misses.isEmpty { missesCard }
                actions
            }
            .padding(20)
        }
        .navigationBarBackButtonHidden()
        .task {
            onAppear()
            // After onAppear: the completion event it records is what moves
            // this scenario's depth on, and the recap says where that lands.
            if let id = plan.scenarioId { brief = try? bridge.lesson(scenarioId: id) }
            words = (try? bridge.vocabulary()) ?? []
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 36))
                .foregroundStyle(Color.mSage)
            Text(brief?.label ?? "Sessione completata")
                .font(.title2.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(Color.mCharcoal)
            // The author's sign-off for this scenario, which is the closest
            // thing the lesson has to a last word.
            if let outro = brief?.outro, !outro.isEmpty {
                Text(outro)
                    .font(.subheadline)
                    .foregroundStyle(Color.mTextMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    private var scoreCard: some View {
        HStack(spacing: 0) {
            RecapStat(value: "\(tally.correct)/\(tally.scored)", label: "corrette")
            RecapStat(value: "\(percentage)%", label: "punteggio")
            RecapStat(value: "\(tally.newWords.count)", label: "parole nuove")
        }
        .card(padding: 16)
    }

    private var coveredCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Eyebrow(text: "Covered")
            if let brief, !brief.grammar.isEmpty {
                RecapList(title: "Grammatica", items: brief.grammar.map(\.label))
            }
            if let brief, !brief.functions.isEmpty {
                RecapList(title: "Comunicazione", items: brief.functions.map(\.label))
            }
            // A short lesson means the pack ran out, not that the lesson was
            // short. Say so rather than letting it read as complete.
            if !plan.shortfalls.isEmpty {
                Label(
                    "Some activities were skipped — this lesson doesn't have "
                        + "enough content yet.",
                    systemImage: "tray"
                )
                .font(.caption)
                .foregroundStyle(Color.mTextMuted)
                .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    private var wordsCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Eyebrow(text: "Parole nuove")
            Text("These words are now in your vocabulary, ready to review.")
                .font(.caption)
                .foregroundStyle(Color.mTextMuted)
            ForEach(newWords.prefix(wordsShown)) { word in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(word.lemma)
                        .font(.callout.weight(.medium))
                        .foregroundStyle(Color.mCharcoal)
                    Text(word.gloss)
                        .font(.caption)
                        .foregroundStyle(Color.mTextMuted)
                    Spacer(minLength: 0)
                    Badge(text: word.cefrLevel)
                }
            }
            // A passage can hand over fifty words at once. The full list
            // belongs on the Vocabulary tab, not at the end of a lesson.
            if newWords.count > wordsShown {
                Text("+ \(newWords.count - wordsShown) more — see the Vocabulary tab")
                    .font(.caption)
                    .foregroundStyle(Color.mTextMuted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    private let wordsShown = 12

    private var missesCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Eyebrow(text: "Da rivedere")
            ForEach(tally.misses) { miss in
                VStack(alignment: .leading, spacing: 4) {
                    Text(miss.prompt)
                        .font(.footnote)
                        .foregroundStyle(Color.mTextMuted)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 8) {
                        Text(miss.answer.isEmpty ? "—" : miss.answer)
                            .strikethrough()
                            .foregroundStyle(Color.mError)
                        Image(systemName: "arrow.right")
                            .font(.caption)
                            .foregroundStyle(Color.mTextMuted)
                        Text(miss.expected)
                            .foregroundStyle(Color.mSuccess)
                    }
                    .font(.callout)
                    .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    private var actions: some View {
        VStack(spacing: 10) {
            if let onNextLesson {
                Button {
                    onNextLesson()
                } label: {
                    Text("Prossima lezione").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
            Button {
                dismiss()
            } label: {
                Text("Fine").frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            .tint(.mTextMuted)
        }
    }

    /// The session's new words, resolved against the vocabulary so each one
    /// can be shown with its gloss rather than as a bare lemma.
    private var newWords: [VocabEntry] {
        let seen = Set(tally.newWords)
        return words.filter { seen.contains($0.lemma) }
    }

    private var percentage: Int {
        tally.scored == 0 ? 0 : Int((Double(tally.correct) / Double(tally.scored) * 100).rounded())
    }
}

private struct RecapStat: View {
    let value: String
    let label: String

    var body: some View {
        VStack(spacing: 2) {
            Text(value)
                .font(.title3.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(Color.mCharcoal)
            Text(label)
                .font(.caption2)
                .foregroundStyle(Color.mTextMuted)
        }
        .frame(maxWidth: .infinity)
    }
}

private struct RecapList: View {
    let title: String
    let items: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(Color.mTextMuted)
            ForEach(items, id: \.self) { item in
                HStack(alignment: .top, spacing: 8) {
                    Circle()
                        .fill(Color.mGold)
                        .frame(width: 5, height: 5)
                        .padding(.top, 6)
                    Text(item)
                        .font(.callout)
                        .foregroundStyle(Color.mText)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
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
                    VocabCardFace(
                        front: payload.front,
                        back: payload.back,
                        example: payload.example,
                        exampleGloss: payload.exampleGloss,
                        revealed: revealed)
                }
                .frame(maxWidth: .infinity)
                .card(padding: 28)

                Spacer()
                if revealed {
                    SrsRatingButtons(onGrade: grade)
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
                VStack(alignment: .leading, spacing: 14) {
                    Eyebrow(text: "Speaking")
                    if let path = payload.image,
                        let art = bridge.media(at: path).flatMap(UIImage.init(data:)) {
                        Image(uiImage: art)
                            .resizable()
                            .scaledToFill()
                            .frame(maxWidth: .infinity)
                            .frame(maxHeight: 180)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    Text(payload.prompt)
                        .font(.callout)
                        .foregroundStyle(Color.mText)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    SpeakingPracticeView(
                        bridge: bridge,
                        itemId: activity.itemId,
                        target: payload.targetText,
                        evidenceJson: bridge.evidence(for: activity.itemId),
                        feedback: feedback,
                        prompt: payload.prompt,
                        level: level)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .card()
                Spacer()
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
