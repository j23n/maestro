import SwiftUI
import ItalianCore
import PackKit
import PracticeKit

/// Practice after a text (HANDOFF.md 3.9): a short intro, the drills one by one with stepped
/// feedback, then a summary that offers the topics the learner needed help with for Remember.
/// Nothing here is scored or stored.
struct PracticeView: View {
    let textID: String

    @Environment(AppModel.self) private var model
    @State private var started = false
    @State private var index = 0
    @State private var outcomes: [String: Outcome] = [:]
    @State private var round = 0

    var body: some View {
        Group {
            if let text = model.text(textID), !text.practice.isEmpty {
                let drills = text.practice
                if !started {
                    PracticeIntro(text: text, drills: drills) { started = true }
                } else if index < drills.count {
                    DrillScreen(text: text, drill: drills[index], number: index + 1, total: drills.count,
                                seed: "\(text.id).\(drills[index].id).\(round)") { outcome in
                        outcomes[drills[index].id] = outcome
                    } onContinue: {
                        index += 1
                    }
                    .id("\(round).\(drills[index].id)")
                } else {
                    PracticeSummaryView(text: text, drills: drills, outcomes: outcomes) {
                        outcomes = [:]
                        index = 0
                        round += 1
                    }
                }
            } else {
                EmptyState(title: "No practice for this text", message: "", systemImage: "pencil.and.list.clipboard")
            }
        }
        .background(Theme.background)
        .navigationTitle("Practice")
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
    }
}

// MARK: Intro

/// The grammar point of the set, with the text's own sentences that carry it.
struct PracticeIntro: View {
    let text: ReadingText
    let drills: [Drill]
    let start: () -> Void

    @Environment(AppModel.self) private var model

    private var mainTopics: [String] {
        var seen: Set<String> = []
        return drills.filter { !$0.isRecycled }.map(\.topic).filter { seen.insert($0).inserted }
    }

    private var recycledTopics: [String] {
        var seen: Set<String> = Set(mainTopics)
        return drills.filter(\.isRecycled).map(\.topic).filter { seen.insert($0).inserted }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 6) {
                    KindTag(kind: .grammar)
                    LevelTag(level: text.level)
                }
                ForEach(mainTopics, id: \.self) { topic in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(model.grammarTitle(topic))
                            .font(.system(size: 26, weight: .bold))
                        if let summary = model.grammarTopic(topic)?.summary {
                            Text(markdown: summary).foregroundStyle(.secondary)
                        }
                    }
                }
                let examples = exampleDrills
                if !examples.isEmpty {
                    SectionLabel("In this text")
                    ForEach(examples) { drill in
                        if let sentence = text.sentence(drill.sentence) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(PracticeText.highlighted(sentence.text, range: drill.r))
                                    .font(.system(.title3, design: .serif))
                                Text(sentence.translation).font(.footnote).foregroundStyle(.secondary)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(12)
                            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12))
                        }
                    }
                }
                if !recycledTopics.isEmpty {
                    SectionLabel("Also in this set")
                    Text(recycledTopics.map { model.grammarTitle($0) }.joined(separator: ", "))
                        .foregroundStyle(.secondary)
                }
            }
            .padding(20)
            .frame(maxWidth: 640, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: 4) {
                Button(action: start) {
                    Text("Start · \(drills.count) drills")
                }
                .buttonStyle(PrimaryButtonStyle())
                .keyboardShortcut(.defaultAction)
                .accessibilityIdentifier("practice.start")
                if let topic = mainTopics.first {
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

    /// Up to three drills of the main topic that have a gap, one per sentence.
    private var exampleDrills: [Drill] {
        var seen: Set<String> = []
        return drills.filter { !$0.isRecycled && $0.r != nil && seen.insert($0.sentence).inserted }.prefix(3).map { $0 }
    }
}

// MARK: Text helpers

enum PracticeText {
    /// Italian text with one range in the accent colour, semibold.
    static func highlighted(_ string: String, range: UTF16Range?) -> AttributedString {
        var a = AttributedString(string)
        a.languageIdentifier = "it-IT"
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
        a.languageIdentifier = "it-IT"
        return a
    }
}

/// Where the reader and the questions offer practice.
enum PracticeEntry {
    /// The topic a text's practice set is about, or nil when the text has none.
    static func topic(of text: ReadingText) -> String? {
        let drills = text.practice
        return (drills.first { !$0.isRecycled } ?? drills.first)?.topic
    }
}
