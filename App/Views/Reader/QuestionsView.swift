import SwiftData
import SwiftUI
import PackKit
import SyncLogic

/// Comprehension questions (HANDOFF.md 3.7): Italian with an English toggle; a wrong pick shows the
/// sentence that answers it.
struct QuestionsView: View {
    let textID: String

    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @Environment(\.modelContext) private var context
    @State private var english = false
    @State private var picks: [String: Int] = [:]

    var body: some View {
        if let text = model.text(textID) {
            List {
                Section {
                    Toggle("Show in English", isOn: $english)
                }
                ForEach(Array(text.questions.enumerated()), id: \.element.id) { n, question in
                    Section {
                        Text(english ? question.promptEN : question.prompt)
                            .font(.system(.body, design: .serif).weight(.semibold))
                            .italianUnless(english)
                        ForEach(Array(question.choices(english: english).enumerated()), id: \.offset) { i, choice in
                            choiceRow(question, index: i, label: choice)
                        }
                        if let pick = picks[question.id], !question.isCorrect(pick) {
                            answerHint(question, text: text)
                        }
                    } header: {
                        SectionLabel("Question \(n + 1) of \(text.questions.count)")
                    }
                }
                if !text.questions.isEmpty {
                    let correct = text.questions.filter { q in picks[q.id].map(q.isCorrect) ?? false }.count
                    Section {
                        Text("\(correct) of \(text.questions.count) right")
                            .font(.headline)
                    }
                }
            }
            .plainPage()
            .navigationTitle("Questions")
            .onAppear { loadAnswers() }
        } else {
            EmptyState(title: "Text not available", message: "", systemImage: "doc.questionmark")
        }
    }

    private func choiceRow(_ q: Question, index: Int, label: String) -> some View {
        let picked = picks[q.id]
        let isPicked = picked == index
        let showCorrect = picked != nil && q.isCorrect(index)
        return Button {
            picks[q.id] = index
            RememberStore(context: context, prefs: prefs, content: model.content)
                .recordAnswer(textID: textID, questionID: q.id, choice: index)
        } label: {
            HStack {
                Text(label).italianUnless(english)
                Spacer()
                if showCorrect {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(Theme.added.foreground)
                        .accessibilityLabel("Correct")
                } else if isPicked {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(Theme.error.foreground)
                        .accessibilityLabel("Wrong")
                }
            }
            .frame(minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRowBackground(showCorrect ? Theme.added.background : (isPicked ? Theme.error.background : nil))
    }

    private func answerHint(_ q: Question, text: ReadingText) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionLabel("The answer is in the text")
            ForEach(q.answerSentences, id: \.self) { sid in
                if let s = text.sentence(sid) {
                    Text(italian: s.text).font(.system(.callout, design: .serif))
                    if english { Text(s.translation).font(.footnote).foregroundStyle(.secondary) }
                }
            }
            NavigationLink(value: Route.text(text.id)) {
                Label("Show in text", systemImage: "text.magnifyingglass")
            }
        }
        .padding(.vertical, 4)
    }

    private func loadAnswers() {
        guard picks.isEmpty, let p = RememberStore(context: context, prefs: prefs, content: model.content).progress(for: textID)
        else { return }
        picks = MergeRules.decodeAnswers(p.answersJSON).mapValues(\.choice)
    }
}

extension View {
    @ViewBuilder func italianUnless(_ english: Bool) -> some View {
        if english { self } else { self.italian() }
    }
}
