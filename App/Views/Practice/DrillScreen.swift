import SwiftUI
import ItalianCore
import PackKit
import PracticeKit

/// One drill: the sentence, the answer controls for its format, and the feedback panel.
struct DrillScreen: View {
    let text: ReadingText
    let drill: Drill
    let number: Int
    let total: Int
    let seed: String
    let onFinish: (Outcome) -> Void
    let onContinue: () -> Void

    @Environment(AppModel.self) private var model
    @State private var feedback = StepFeedback()
    @State private var panel: Panel?
    @State private var typed = ""
    @State private var wrongOptions: Set<String> = []
    @State private var built: [Int] = []
    @State private var matched: [String: String] = [:]
    @State private var selectedLeft: String?
    @State private var badPair: [String] = []
    @State private var missedPair = false
    @FocusState private var fieldFocused: Bool

    /// What the feedback panel says.
    struct Panel: Equatable {
        enum Kind { case success, hint, shown }
        let kind: Kind
        let headline: String
        var detail: String?
    }

    var body: some View {
        VStack(spacing: 0) {
            ProgressView(value: Double(number - (feedback.isDone ? 0 : 1)), total: Double(total))
                .tint(Theme.ink)
                .padding(.horizontal, 20)
                .padding(.top, 8)
                .accessibilityLabel("Drill \(number) of \(total)")
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    tags
                    Text(drill.prompt)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.secondary)
                    content
                    if let panel { panelView(panel) }
                }
                .padding(20)
                .frame(maxWidth: 640, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
            .scrollDismissesKeyboard(.interactively)
            .accessibilityIdentifier("practice.drill")
        }
        .safeAreaInset(edge: .bottom) { actions }
        .onAppear { if drill.format == .gap { fieldFocused = true } }
    }

    // MARK: Pieces

    private var tags: some View {
        HStack(spacing: 6) {
            if drill.isRecycled {
                Tag(text: "Review", colors: Theme.warning)
            }
            Tag(text: model.grammarTitle(drill.topic), colors: Theme.kind(.grammar))
            Spacer()
            Text("\(number) of \(total)").font(.footnote.monospacedDigit()).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder private var content: some View {
        switch drill.format {
        case .choice: choice
        case .gap: gap
        case .match: match
        case .build: build
        case nil: EmptyView()
        }
    }

    private var sentenceText: String { text.sentence(drill.sentence)?.text ?? "" }

    private func stimulus(filled: String?) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(PracticeText.gapped(before: drill.before ?? "", filled: filled, after: drill.after ?? ""))
                .font(.system(.title2, design: .serif))
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("practice.sentence")
            if let cue = drill.cue {
                Text(italian: "(\(cue))").font(.callout).foregroundStyle(.secondary)
            }
            if let translation = text.sentence(drill.sentence)?.translation {
                Text(translation).font(.footnote).foregroundStyle(.secondary)
            }
        }
    }

    // MARK: Choice

    private var choice: some View {
        let options = SeededShuffle.shuffled(drill.options ?? [], seed: seed)
        return VStack(alignment: .leading, spacing: 14) {
            stimulus(filled: feedback.isDone ? drill.answer : nil)
            VStack(spacing: 8) {
                ForEach(Array(options.enumerated()), id: \.offset) { n, option in
                    let isWrong = wrongOptions.contains(option)
                    let isRight = feedback.isDone && (drill.answers ?? []).contains(option)
                    Button {
                        pick(option)
                    } label: {
                        HStack(spacing: 12) {
                            Text("\(n + 1)")
                                .font(.caption.weight(.semibold).monospacedDigit())
                                .frame(width: 22, height: 22)
                                .background(Theme.chip, in: RoundedRectangle(cornerRadius: 6))
                                .accessibilityHidden(true)
                            Text(italian: option).font(.system(.title3, design: .serif))
                            Spacer()
                            if isRight {
                                Image(systemName: "checkmark.circle.fill").accessibilityLabel("Right")
                            } else if isWrong {
                                Image(systemName: "xmark.circle.fill").accessibilityLabel("Wrong")
                            }
                        }
                        .padding(.horizontal, 14)
                        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
                        .foregroundStyle(isRight ? Theme.added.foreground : isWrong ? Theme.error.foreground : Theme.ink)
                        .background(RoundedRectangle(cornerRadius: 12)
                            .fill(isRight ? Theme.added.background : isWrong ? Theme.error.background : Theme.background))
                        .overlay(RoundedRectangle(cornerRadius: 12)
                            .stroke(isRight ? Theme.addedBorder : isWrong ? Theme.error.foreground : Theme.hairline,
                                    lineWidth: 1.5))
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(feedback.isDone || isWrong)
                    .keyboardShortcut(KeyEquivalent(Character("\(n + 1)")), modifiers: [])
                    .accessibilityIdentifier("practice.option.\(n)")
                }
            }
        }
    }

    private func pick(_ option: String) {
        let grade = DrillGrader.grade(option: option, for: drill)
        if grade.isAccepted {
            feedback.record(accepted: true)
            succeed(accentSlip: nil)
        } else {
            wrongOptions.insert(option)
            miss(grade)
        }
    }

    // MARK: Gap

    private var gap: some View {
        VStack(alignment: .leading, spacing: 14) {
            stimulus(filled: feedback.isDone ? (feedback.outcome == .shown ? drill.answer : typedOrAnswer) : nil)
            TextField("Type in Italian", text: $typed)
                .font(.system(.title3, design: .serif))
                .autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .focused($fieldFocused)
                .padding(.horizontal, 14)
                .frame(minHeight: 50)
                .background(RoundedRectangle(cornerRadius: 12).stroke(fieldBorder, lineWidth: 1.5))
                .disabled(feedback.isDone)
                .onSubmit(check)
                .italian()
                .accessibilityIdentifier("practice.answer")
            if !feedback.isDone {
                AccentKeys { typed += $0 }
            }
        }
    }

    private var typedOrAnswer: String {
        let t = typed.trimmingCharacters(in: .whitespaces)
        return t.isEmpty ? drill.answer : t
    }

    private var fieldBorder: Color {
        switch panel?.kind {
        case .success: Theme.addedBorder
        case .hint: Theme.error.foreground
        default: Theme.borderInput
        }
    }

    // MARK: Build

    private var tileBank: [String] {
        SeededShuffle.shuffled((drill.tiles ?? []) + (drill.distractors ?? []), seed: seed, avoidingGivenOrder: true)
    }

    private var build: some View {
        let bank = tileBank
        return VStack(alignment: .leading, spacing: 14) {
            if let translation = drill.translation {
                Text(translation).font(.system(.title3, design: .serif)).italic()
            }
            FlowLayout(spacing: 8) {
                ForEach(Array(built.enumerated()), id: \.offset) { position, index in
                    TileButton(title: bank[index]) {
                        if !feedback.isDone { built.remove(at: position); clearHint() }
                    }
                    .accessibilityIdentifier("practice.built.\(position)")
                }
            }
            .frame(maxWidth: .infinity, minHeight: 60, alignment: .topLeading)
            .padding(8)
            .background(RoundedRectangle(cornerRadius: 12)
                .strokeBorder(fieldBorder, style: StrokeStyle(lineWidth: 1.5, dash: panel == nil ? [5, 4] : [])))
            .accessibilityLabel("Your sentence")
            if !feedback.isDone {
                FlowLayout(spacing: 8) {
                    ForEach(Array(bank.enumerated()), id: \.offset) { index, tile in
                        TileButton(title: tile) {
                            built.append(index)
                            clearHint()
                        }
                        .opacity(built.contains(index) ? 0 : 1)
                        .disabled(built.contains(index))
                        .accessibilityIdentifier("practice.tile.\(index)")
                    }
                }
            }
        }
    }

    private func clearHint() {
        if panel?.kind == .hint { panel = nil }
    }

    // MARK: Match

    private var match: some View {
        let pairs = drill.pairs?.filter { $0.count == 2 } ?? []
        let right = SeededShuffle.shuffled(pairs.map { $0[1] }, seed: seed)
        return HStack(alignment: .top, spacing: 10) {
            VStack(spacing: 8) {
                ForEach(pairs.map { $0[0] }, id: \.self) { left in
                    MatchTile(title: left, state: matched[left] != nil ? .matched
                              : selectedLeft == left ? .selected : badPair.first == left ? .wrong : .idle) {
                        selectedLeft = left
                        badPair = []
                    }
                    .disabled(matched[left] != nil || feedback.isDone)
                }
            }
            VStack(spacing: 8) {
                ForEach(right, id: \.self) { item in
                    let done = matched.values.contains(item)
                    MatchTile(title: item, state: done ? .matched : badPair.last == item ? .wrong : .idle) {
                        pair(item, pairs: pairs)
                    }
                    .disabled(done || feedback.isDone)
                }
            }
        }
    }

    private func pair(_ item: String, pairs: [[String]]) {
        guard let left = selectedLeft, let pair = pairs.first(where: { $0[0] == left }) else { return }
        selectedLeft = nil
        if pair[1] == item {
            matched[left] = item
            badPair = []
            if matched.count == pairs.count {
                feedback.finish(missed: missedPair)
                succeed(accentSlip: nil)
            } else {
                panel = nil
            }
        } else {
            missedPair = true
            badPair = [left, item]
            panel = Panel(kind: .hint, headline: "Not a pair.", detail: "\(left) doesn't go with \(item). Try another.")
        }
    }

    // MARK: Actions

    private var actions: some View {
        VStack(spacing: 4) {
            if feedback.isDone {
                Button(number == total ? "See how it went" : "Continue", action: onContinue)
                    .buttonStyle(PrimaryButtonStyle())
                    .keyboardShortcut(.defaultAction)
                    .accessibilityIdentifier("practice.continue")
            } else {
                if drill.format == .gap || drill.format == .build {
                    Button("Check", action: check)
                        .buttonStyle(PrimaryButtonStyle())
                        .keyboardShortcut(.defaultAction)
                        .disabled(drill.format == .gap ? typed.trimmingCharacters(in: .whitespaces).isEmpty : built.isEmpty)
                        .accessibilityIdentifier("practice.check")
                }
                HStack {
                    if let hint = drill.hint, !feedback.sawHint {
                        Button("Show a hint") {
                            feedback.showHint()
                            panel = Panel(kind: .hint, headline: "Hint", detail: hint)
                        }
                        .accessibilityIdentifier("practice.hint")
                        Spacer()
                    }
                    Button("Show answer", action: reveal)
                        .accessibilityIdentifier("practice.showAnswer")
                }
                .frame(minHeight: 44)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .frame(maxWidth: 640)
        .frame(maxWidth: .infinity)
        .background(Theme.background)
    }

    private func check() {
        guard !feedback.isDone else { return }
        let grade: Grade
        switch drill.format {
        case .gap:
            guard !typed.trimmingCharacters(in: .whitespaces).isEmpty else { return }
            grade = DrillGrader.grade(typed, for: drill)
        case .build:
            guard !built.isEmpty else { return }
            let bank = tileBank
            grade = DrillGrader.grade(tiles: built.map { bank[$0] }, for: drill)
        default:
            return
        }
        switch grade {
        case .correct:
            feedback.record(accepted: true)
            succeed(accentSlip: nil)
        case .accentSlip(let expected):
            feedback.record(accepted: true)
            typed = expected
            succeed(accentSlip: expected)
        case .wrong:
            miss(grade)
        }
    }

    private func miss(_ grade: Grade) {
        guard case .wrong(let hint) = grade else { return }
        if feedback.record(accepted: false) == .retrying {
            panel = Panel(kind: .hint, headline: "Not quite.", detail: hint)
        } else {
            showAnswerPanel()
        }
    }

    private func reveal() {
        feedback.reveal()
        if drill.format == .match {
            for pair in drill.pairs ?? [] where pair.count == 2 { matched[pair[0]] = pair[1] }
        }
        showAnswerPanel()
    }

    private func succeed(accentSlip: String?) {
        let headline = accentSlip.map { "Yes. Watch the accent: \($0)." } ?? (feedback.outcome == .firstTry ? "Yes." : "That's it.")
        panel = Panel(kind: .success, headline: headline, detail: drill.rule)
        finish()
    }

    private func showAnswerPanel() {
        let answer: String
        switch drill.format {
        case .match: answer = (drill.pairs ?? []).filter { $0.count == 2 }.map { "\($0[0]) → \($0[1])" }.joined(separator: ", ")
        default: answer = sentenceText
        }
        panel = Panel(kind: .shown, headline: "Here's the answer.", detail: answer)
        finish()
    }

    private func finish() {
        fieldFocused = false
        if let outcome = feedback.outcome { onFinish(outcome) }
    }

    private func panelView(_ panel: Panel) -> some View {
        let colors: Theme.Pair = switch panel.kind {
        case .success: Theme.added
        case .hint: Theme.warning
        case .shown: Theme.error
        }
        return VStack(alignment: .leading, spacing: 6) {
            Text(panel.headline).font(.headline)
            if let detail = panel.detail {
                if panel.kind == .shown {
                    Text(italian: detail).font(.system(.body, design: .serif))
                    if let rule = drill.rule, drill.format != .build {
                        Text(markdown: rule).font(.callout)
                    }
                } else {
                    Text(markdown: detail).font(.callout)
                }
            }
        }
        .foregroundStyle(colors.foreground)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(colors.background, in: RoundedRectangle(cornerRadius: 14))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("practice.feedback")
    }
}

// MARK: Small controls

/// à è é ì ò ù, appended to the answer.
struct AccentKeys: View {
    let insert: (String) -> Void

    var body: some View {
        HStack(spacing: 6) {
            ForEach(["à", "è", "é", "ì", "ò", "ù"], id: \.self) { c in
                Button { insert(c) } label: {
                    Text(c).font(.system(.title3, design: .serif))
                        .frame(width: 44, height: 40)
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 10))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Type \(c)")
            }
        }
    }
}

struct TileButton: View {
    let title: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(italian: title)
                .font(.system(.title3, design: .serif))
                .padding(.horizontal, 12)
                .frame(minHeight: 44)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.hairline))
        }
        .buttonStyle(.plain)
    }
}

struct MatchTile: View {
    enum Look { case idle, selected, matched, wrong }
    let title: String
    let state: Look
    let action: () -> Void

    var body: some View {
        let colors: (Color, Color, Color) = switch state {
        case .idle: (Theme.background, Theme.ink, Theme.hairline)
        case .selected: (Theme.selectionFill, Theme.ink, Theme.accent)
        case .matched: (Theme.added.background, Theme.added.foreground, Theme.addedBorder)
        case .wrong: (Theme.error.background, Theme.error.foreground, Theme.error.foreground)
        }
        Button(action: action) {
            Text(italian: title)
                .font(.system(.body, design: .serif))
                .multilineTextAlignment(.center)
                .padding(.horizontal, 8)
                .frame(maxWidth: .infinity, minHeight: 48)
                .foregroundStyle(colors.1)
                .background(colors.0, in: RoundedRectangle(cornerRadius: 12))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(colors.2, lineWidth: 1.5))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(state == .selected ? .isSelected : [])
    }
}

/// Lays out tiles left to right, wrapping to new lines.
struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, lineHeight: CGFloat = 0, maxX: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width {
                x = 0
                y += lineHeight + spacing
                lineHeight = 0
            }
            x += size.width + spacing
            maxX = max(maxX, x - spacing)
            lineHeight = max(lineHeight, size.height)
        }
        return CGSize(width: proposal.width ?? maxX, height: y + lineHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, lineHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX {
                x = bounds.minX
                y += lineHeight + spacing
                lineHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
    }
}
