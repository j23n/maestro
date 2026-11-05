import SwiftData
import SwiftUI
import LanguageCore
import PackKit
import PracticeKit

/// A session after a text (HANDOFF.md 3.9): a plan, then Questions, Words, Grammar, Verbs, Say it and
/// Review, each stage with a short intro and its drills, then a wrap-up. Every drill's outcome is kept on
/// this device (`DrillLog`) so that what needed help comes back in Review. No scores.
struct SessionView: View {
    let textID: String

    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @Environment(\.modelContext) private var context
    @State private var stages: [SessionStage] = []
    @State private var step: Step = .plan
    @State private var outcomes: [String: Outcome] = [:]
    @State private var startedAt = Date.now
    @State private var minutes = 1
    @State private var round = 0
    @State private var review: [SessionDrill]?

    enum Step: Hashable {
        case plan
        case intro(Int)
        case questions(Int)
        case drill(Int, Int)
        case done
    }

    var body: some View {
        Group {
            if let text = model.text(textID), !text.practice.isEmpty || !text.questions.isEmpty {
                content(text)
            } else {
                EmptyState(title: "No practice for this text", message: "", systemImage: "pencil.and.list.clipboard")
            }
        }
        .background(Theme.background)
        .navigationTitle("Practice")
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .onAppear {
            if review == nil { review = loadReview() }
        }
    }

    @ViewBuilder private func content(_ text: ReadingText) -> some View {
        switch step {
        case .plan:
            SessionPlanView(text: text, review: review ?? [], build: { build(text, settings: $0) }) {
                stages = build(text, settings: Self.settings(prefs))
                outcomes = [:]
                startedAt = .now
                begin(0)
            }
        case .intro(let s):
            if stages.indices.contains(s) {
                StageIntroView(text: text, stage: stages[s], introduces: model.introduces(text.id)) {
                    step = .drill(s, 0)
                }
                .id("intro.\(round).\(s)")
            }
        case .questions(let s):
            QuestionsView(textID: text.id, inSession: true)
                .safeAreaInset(edge: .bottom) {
                    Button("Continue") { begin(s + 1) }
                        .buttonStyle(PrimaryButtonStyle())
                        .accessibilityIdentifier("session.questionsDone")
                        .padding(.horizontal, 20)
                        .padding(.vertical, 10)
                        .frame(maxWidth: 640)
                        .frame(maxWidth: .infinity)
                        .background(Theme.background)
                }
        case .drill(let s, let d):
            if stages.indices.contains(s), stages[s].drills.indices.contains(d),
               let drillText = model.text(stages[s].drills[d].textID) {
                let stage = stages[s]
                let item = stage.drills[d]
                DrillScreen(text: drillText, drill: item.drill, stage: stage.kind, number: d + 1,
                            total: stage.drills.count, seed: "\(item.id).\(round)") { outcome in
                    record(item, outcome)
                } onContinue: {
                    if d + 1 < stage.drills.count { step = .drill(s, d + 1) } else { begin(s + 1) }
                }
                .id("\(round).\(item.id)")
            }
        case .done:
            SessionSummaryView(text: text, stages: stages, outcomes: outcomes, minutes: minutes) {
                round += 1
                review = loadReview()
                step = .plan
            }
        }
    }

    /// Opens stage `s`: Questions straight away, the others with their intro; past the last, the wrap-up.
    private func begin(_ s: Int) {
        guard stages.indices.contains(s) else {
            minutes = max(1, Int((Date.now.timeIntervalSince(startedAt) / 60).rounded()))
            step = .done
            return
        }
        step = stages[s].kind == .questions ? .questions(s) : .intro(s)
    }

    private func build(_ text: ReadingText, settings: SessionSettings) -> [SessionStage] {
        SessionBuilder.stages(textID: text.id, drills: text.practice, hasQuestions: !text.questions.isEmpty,
                              introduces: model.introduces(text.id), settings: settings, review: review ?? [])
    }

    /// The plan screen's choices, from the synced preferences.
    static func settings(_ prefs: Preferences) -> SessionSettings {
        let off = prefs.sessionOff
        return SessionSettings(length: prefs.sessionShort ? .short : .full,
                               strands: Set(Strand.allCases.filter { !off.contains($0.rawValue) }),
                               questions: !off.contains(StageKind.questions.rawValue),
                               review: !off.contains(StageKind.review.rawValue))
    }

    private func record(_ item: SessionDrill, _ outcome: Outcome) {
        guard outcomes[item.id] == nil else { return }
        outcomes[item.id] = outcome
        // Only drills with a stable key can be found again for Review.
        guard item.drill.key != nil else { return }
        RememberStore(context: context, prefs: prefs, content: model.content)
            .recordDrill(textID: item.textID, drill: item.drill, outcome: outcome)
    }

    /// Drills of earlier texts that needed help, still in the library.
    private func loadReview() -> [SessionDrill] {
        let store = RememberStore(context: context, prefs: prefs, content: model.content)
        let records = ReviewPicker.pick(store.drillRecords(language: prefs.language), excluding: textID, limit: 20)
        var out: [SessionDrill] = []
        for record in records where out.count < SessionBuilder.reviewLimit {
            guard let text = model.text(record.textID), let drill = text.drill(key: record.drillKey),
                  ReviewPicker.canReview(drill) else { continue }
            out.append(SessionDrill(textID: record.textID, drill: drill))
        }
        return out
    }
}

// MARK: Plan

/// What the session holds: Short or Full, and a switch for each stage. The choices are remembered.
struct SessionPlanView: View {
    let text: ReadingText
    let review: [SessionDrill]
    let build: (SessionSettings) -> [SessionStage]
    let start: () -> Void

    @Environment(Preferences.self) private var prefs

    var body: some View {
        let counts = SessionBuilder.counts(text.practice)
        let planned = build(SessionView.settings(prefs))
        let total = planned.reduce(0) { $0 + $1.drills.count }
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 6) {
                    LevelTag(level: text.level)
                    Text("Practise this text").font(.system(size: 26, weight: .bold))
                    Text(target: text.title).font(.system(.body, design: .serif)).foregroundStyle(.secondary)
                }
                Picker("Length", selection: Binding(get: { prefs.sessionShort }, set: { prefs.sessionShort = $0 })) {
                    Text("Short").tag(true)
                    Text("Full").tag(false)
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("session.length")
                Text(prefs.sessionShort ? "The core drills of each stage, a few minutes."
                     : "Every drill the text has.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                SectionLabel("Stages")
                VStack(spacing: 0) {
                    ForEach(StageKind.allCases) { kind in
                        if let count = stageCount(kind, counts: counts) {
                            stageRow(kind, count: count)
                            Divider()
                        }
                    }
                }
            }
            .padding(20)
            .frame(maxWidth: 640, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .safeAreaInset(edge: .bottom) {
            Button(action: start) {
                Text(total == 0 ? "Start" : "Start · \(total) drills")
            }
            .buttonStyle(PrimaryButtonStyle())
            .keyboardShortcut(.defaultAction)
            .disabled(planned.isEmpty)
            .accessibilityIdentifier("practice.start")
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
            .background(Theme.background)
        }
    }

    /// What a stage row says it holds, or nil when the text has nothing for the stage.
    private func stageCount(_ kind: StageKind, counts: [Strand: (short: Int, full: Int)]) -> String? {
        switch kind {
        case .questions:
            return text.questions.isEmpty ? nil : "\(text.questions.count) questions"
        case .review:
            return review.isEmpty ? nil : "\(min(review.count, SessionBuilder.reviewLimit)) from earlier texts"
        default:
            guard let strand = kind.strand, let n = counts[strand] else { return nil }
            let shown = prefs.sessionShort ? n.short : n.full
            return shown == 1 ? "1 drill" : "\(shown) drills"
        }
    }

    private func stageRow(_ kind: StageKind, count: String) -> some View {
        Toggle(isOn: Binding(get: { !prefs.sessionOff.contains(kind.rawValue) },
                             set: { on in
                                 var off = prefs.sessionOff
                                 if on { off.remove(kind.rawValue) } else { off.insert(kind.rawValue) }
                                 prefs.sessionOff = off
                             })) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Tag(text: kind.title, colors: Theme.stage(kind))
                    Text(count).font(.footnote.monospacedDigit()).foregroundStyle(.secondary)
                }
                Text(StageIntroView.about(kind)).font(.subheadline).foregroundStyle(.secondary)
            }
        }
        .frame(minHeight: 56)
        .padding(.vertical, 4)
        .accessibilityIdentifier("session.stage.\(kind.rawValue)")
    }
}

// MARK: Stage intro

/// The page before a stage's drills: what it practises, and what from the text it uses.
struct StageIntroView: View {
    let text: ReadingText
    let stage: SessionStage
    let introduces: [String]
    let start: () -> Void

    @Environment(AppModel.self) private var model

    static func about(_ kind: StageKind) -> String {
        switch kind {
        case .questions: "Check you followed the text."
        case .words: "New words from the text: what they mean, how they're spelled and how they sound."
        case .grammar: "The text's grammar point, in its own sentences."
        case .verbs: "The text's verbs: spot them, conjugate them, recall them."
        case .say: "Say what the people in the text say, then take a part in their conversation."
        case .review: "Drills from earlier texts that needed help."
        }
    }

    /// The grammar topics the intro explains: the Grammar stage's, or the introduced ones when the
    /// stage stands in for Grammar.
    private var topics: [String] {
        if stage.kind == .grammar {
            var seen: Set<String> = []
            let own = stage.drills.map(\.drill).filter { !$0.isRecycled }.map(\.topic).filter { seen.insert($0).inserted }
            return own.isEmpty ? introduces : own
        }
        return stage.introducesGrammar ? introduces : []
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 6) {
                    Tag(text: stage.kind.title, colors: Theme.stage(stage.kind))
                    Text(stage.drills.count == 1 ? "1 drill" : "\(stage.drills.count) drills")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Text(Self.about(stage.kind)).font(.title3.weight(.semibold))
                ForEach(topics, id: \.self) { topic in
                    grammar(topic)
                }
                details
            }
            .padding(20)
            .frame(maxWidth: 640, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: 4) {
                Button("Start", action: start)
                    .buttonStyle(PrimaryButtonStyle())
                    .keyboardShortcut(.defaultAction)
                    .accessibilityIdentifier("session.stageStart")
                if let topic = topics.first {
                    NavigationLink(value: Route.grammar(topic)) {
                        Text("Open the grammar page").frame(maxWidth: .infinity, minHeight: 44)
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
            .background(Theme.background)
        }
    }

    /// A grammar point: its title and summary, and up to three of the text's sentences that carry it.
    private func grammar(_ topic: String) -> some View {
        var seen: Set<String> = []
        let examples = text.practice.filter { $0.topic == topic && $0.r != nil && seen.insert($0.sentence).inserted }.prefix(3)
        return VStack(alignment: .leading, spacing: 10) {
            Text(model.grammarTitle(topic)).font(.system(size: 24, weight: .bold))
            if let summary = model.grammarTopic(topic)?.summary {
                Text(markdown: summary).foregroundStyle(.secondary)
            }
            if !examples.isEmpty {
                SectionLabel("In this text")
                ForEach(Array(examples)) { drill in
                    if let sentence = text.sentence(drill.sentence) {
                        exampleRow(sentence, range: drill.r)
                    }
                }
            }
        }
    }

    private func exampleRow(_ sentence: Sentence, range: UTF16Range?) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(PracticeText.highlighted(sentence.text, range: range))
                .font(.system(.title3, design: .serif))
            Text(sentence.translation).font(.footnote).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12))
    }

    /// What the stage uses from the text: its new words, its verbs or its functions.
    @ViewBuilder private var details: some View {
        switch stage.kind {
        case .words:
            if let words = text.newWords, !words.isEmpty {
                SectionLabel("New in this text")
                ForEach(words, id: \.self) { word in
                    pairRow(word.word, word.gloss)
                }
            }
        case .verbs:
            if let verbs = text.verbs, !verbs.isEmpty {
                SectionLabel("Verbs in this text")
                ForEach(verbs, id: \.self) { verb in
                    pairRow("\(verb.word) → \(verb.surface)",
                            FormTag(verb.form)?.label(in: TargetLanguage.current) ?? "")
                }
            }
        case .say:
            if let functions = text.functions, !functions.isEmpty {
                SectionLabel("In this conversation")
                ForEach(functions, id: \.self) { function in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(function.name).font(.body)
                        Text(target: function.label).font(.footnote).foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        case .questions, .grammar, .review:
            EmptyView()
        }
    }

    private func pairRow(_ target: String, _ english: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(target: target).font(.system(.body, design: .serif))
            Spacer(minLength: 12)
            Text(english).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.trailing)
        }
        .accessibilityElement(children: .combine)
    }
}

// MARK: Text helpers

enum PracticeText {
    /// Target-language text with one range in the accent colour, semibold.
    static func highlighted(_ string: String, range: UTF16Range?) -> AttributedString {
        var a = AttributedString(string)
        a.languageIdentifier = TargetLanguage.current.bcp47
        if let r = range, let span = Range(NSRange(location: r.start, length: r.length), in: a) {
            a[span].foregroundColor = Theme.accent
            a[span].inlinePresentationIntent = .stronglyEmphasized
        }
        return a
    }

    /// The sentence with its gap: blank while answering, filled once the drill is done.
    static func gapped(before: String, filled: String?, after: String) -> AttributedString {
        var a = AttributedString(before)
        var gap = AttributedString(filled ?? "\u{2007}\u{2007}\u{2007}\u{2007}\u{2007}\u{2007}")
        gap.underlineStyle = Text.LineStyle(pattern: .solid)
        gap.foregroundColor = Theme.accent
        gap.inlinePresentationIntent = .stronglyEmphasized
        a += gap
        a += AttributedString(after)
        a.languageIdentifier = TargetLanguage.current.bcp47
        return a
    }
}

/// Where the reader and the questions offer a session.
enum PracticeEntry {
    /// Whether a text has drills to practise.
    static func hasPractice(_ text: ReadingText) -> Bool { !text.practice.isEmpty }
}
