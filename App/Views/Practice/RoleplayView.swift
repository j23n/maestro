import SwiftUI
import LanguageCore
import PackKit
import PracticeKit

/// A role-play (HANDOFF.md 3.9): the text's conversation, with the learner taking one side. The other
/// side's lines appear on their own; at each of the learner's turns they pick a reply or type one.
/// `RoleplayState` grades it; this view only renders it.
struct RoleplayView: View {
    let text: ReadingText
    let drill: Drill
    let seed: String
    /// Set by the drill's "Show the conversation": plays every remaining turn out with the text's lines.
    let revealAll: Bool
    let onDone: (Outcome) -> Void

    @Environment(AppModel.self) private var model
    @State private var state: RoleplayState
    @State private var typed = ""
    @State private var reported = false
    @FocusState private var fieldFocused: Bool

    init(text: ReadingText, drill: Drill, seed: String, revealAll: Bool, onDone: @escaping (Outcome) -> Void) {
        self.text = text
        self.drill = drill
        self.seed = seed
        self.revealAll = revealAll
        self.onDone = onDone
        let lines: @Sendable ([String]) -> String = { ids in
            ids.compactMap { text.sentence($0)?.text }.joined(separator: " ")
        }
        _state = State(initialValue: RoleplayState(drill: drill, text: lines))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let speaker = drill.speaker {
                Text("You're \(speaker)\(drill.other.map { ", talking to \($0)" } ?? "").")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            goals
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(state.transcript.enumerated()), id: \.offset) { _, line in
                    bubble(line)
                }
            }
            .accessibilityIdentifier("roleplay.transcript")
            if !state.isDone {
                reply
            }
        }
        .onChange(of: revealAll) { _, reveal in
            guard reveal else { return }
            while !state.isDone { state.reveal() }
            report()
        }
        .onChange(of: state.isDone) { _, done in
            if done { report() }
        }
        .onAppear {
            if state.isDone { report() }
        }
    }

    private func report() {
        guard state.isDone, !reported else { return }
        reported = true
        fieldFocused = false
        onDone(state.outcome)
    }

    // MARK: Goals

    @ViewBuilder private var goals: some View {
        let goals = drill.goals ?? []
        if !goals.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text("Your goals").font(.footnote.weight(.semibold)).foregroundStyle(.secondary)
                ForEach(goals) { goal in
                    let done = state.reached.contains(goal.id)
                    Label {
                        Text(goal.label).strikethrough(done)
                    } icon: {
                        Image(systemName: done ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(done ? Theme.added.foreground : Theme.borderControl)
                    }
                    .font(.subheadline)
                    .accessibilityElement(children: .combine)
                    .accessibilityValue(done ? "Done" : "Not yet")
                }
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12))
        }
    }

    // MARK: Lines

    private func bubble(_ line: RoleplayState.Line) -> some View {
        HStack(alignment: .bottom) {
            if line.isLearner { Spacer(minLength: 40) }
            VStack(alignment: line.isLearner ? .trailing : .leading, spacing: 3) {
                Text(line.isLearner ? "You" : line.who)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(target: line.text)
                        .font(.system(.body, design: .serif))
                        .fixedSize(horizontal: false, vertical: true)
                    if !line.isLearner {
                        Button {
                            model.speech.say(line.text)
                        } label: {
                            Image(systemName: "speaker.wave.2")
                                .frame(width: 44, height: 44)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Play \(line.who)'s line")
                    }
                }
                if line.shown {
                    Text("You could say this").font(.caption).foregroundStyle(Theme.error.foreground)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, line.isLearner ? 10 : 2)
            .foregroundStyle(line.isLearner ? (line.shown ? Theme.error.foreground : Theme.added.foreground) : Theme.ink)
            .background(RoundedRectangle(cornerRadius: 14)
                .fill(line.isLearner ? (line.shown ? Theme.error.background : Theme.added.background) : Theme.surface))
            if !line.isLearner { Spacer(minLength: 40) }
        }
    }

    // MARK: Reply

    private var reply: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Your turn").font(.footnote.weight(.semibold)).foregroundStyle(.secondary)
            let chips = state.chips(seed: seed)
            FlowLayout(spacing: 8) {
                ForEach(Array(chips.enumerated()), id: \.offset) { n, chip in
                    let wrong = state.wrongChips.contains(chip)
                    Button {
                        state.pick(chip)
                        typed = ""
                    } label: {
                        Text(target: chip)
                            .font(.system(.body, design: .serif))
                            .padding(.horizontal, 12)
                            .frame(minHeight: 44)
                            .foregroundStyle(wrong ? Theme.error.foreground : Theme.ink)
                            .background(RoundedRectangle(cornerRadius: 22)
                                .fill(wrong ? Theme.error.background : Theme.background))
                            .overlay(RoundedRectangle(cornerRadius: 22)
                                .stroke(wrong ? Theme.error.foreground : Theme.hairline, lineWidth: 1.5))
                    }
                    .buttonStyle(.plain)
                    .disabled(wrong)
                    .accessibilityIdentifier("roleplay.chip.\(n)")
                }
            }
            HStack(spacing: 8) {
                TextField("Or type your reply", text: $typed)
                    .font(.system(.body, design: .serif))
                    .autocorrectionDisabled()
                    .focused($fieldFocused)
                    .padding(.horizontal, 12)
                    .frame(minHeight: 44)
                    .background(RoundedRectangle(cornerRadius: 12).stroke(Theme.borderInput, lineWidth: 1.5))
                    .onSubmit(send)
                    .targetLanguage()
                    .accessibilityIdentifier("roleplay.reply")
                Button(action: send) {
                    Image(systemName: "arrow.up.circle.fill").font(.title)
                        .frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .disabled(typed.trimmingCharacters(in: .whitespaces).isEmpty)
                .accessibilityLabel("Send")
                .accessibilityIdentifier("roleplay.send")
            }
            if let hint = state.hint {
                Text(hint)
                    .font(.callout)
                    .foregroundStyle(Theme.warning.foreground)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.warning.background, in: RoundedRectangle(cornerRadius: 10))
            }
            Button("Show me this line") {
                state.reveal()
                typed = ""
            }
            .frame(minHeight: 44)
            .accessibilityIdentifier("roleplay.showLine")
        }
        .padding(12)
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.hairline))
    }

    private func send() {
        let reply = typed.trimmingCharacters(in: .whitespaces)
        guard !reply.isEmpty, !state.isDone else { return }
        let turn = state.current
        let grade = state.say(reply)
        if case .wrong = grade, state.current == turn { return }
        typed = ""
    }
}
