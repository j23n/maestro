import SwiftUI
import LanguageCore
import PackKit
import PracticeKit

/// One drill of a session: the sentence, the answer controls for its format, and the feedback panel
/// (HANDOFF.md 3.9). A role-play runs in `RoleplayView` inside it.
struct DrillScreen: View {
    let text: ReadingText
    let drill: Drill
    let stage: StageKind
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
    @State private var picked: Set<DrillTarget> = []
    @State private var cells: [String: String] = [:]
    @State private var wrongCells: Set<String> = []
    @State private var roleplayDone: Outcome?
    @State private var revealRoleplay = false
    @FocusState private var fieldFocused: Bool
    @FocusState private var focusedCell: String?

    /// What the feedback panel says.
    struct Panel: Equatable {
        enum Kind { case success, hint, shown }
        let kind: Kind
        let headline: String
        var detail: String?
        var also: [String] = []
    }

    var body: some View {
        VStack(spacing: 0) {
            ProgressView(value: Double(number - (isDone ? 0 : 1)), total: Double(max(total, 1)))
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
        .onAppear {
            if [.gap, .listen, .say].contains(drill.format) { fieldFocused = true }
            if drill.format == .listen, let word = drill.speak { model.speech.say(word) }
        }
    }

    private var isDone: Bool { drill.format == .roleplay ? roleplayDone != nil : feedback.isDone }

    // MARK: Pieces

    private var tags: some View {
        HStack(spacing: 6) {
            Tag(text: stage.title, colors: Theme.stage(stage))
            if let detail = tagDetail {
                Text(detail).font(.footnote).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            Text("\(number) of \(total)").font(.footnote.monospacedDigit()).foregroundStyle(.secondary)
        }
    }

    /// The topic, verb or function the drill is about, beside the stage tag.
    private var tagDetail: String? {
        switch drill.strandKind {
        case .grammar: (drill.isRecycled ? "Review: " : "") + model.grammarTitle(drill.topic)
        case .verbs: drill.lemma.map(LemmaID.headword(of:))
        case .words: nil
        case .say: drill.label ?? text.functions?.first { $0.id == drill.function }?.name
        }
    }

    @ViewBuilder private var content: some View {
        switch drill.format {
        case .choice: choice
        case .gap: gap
        case .listen: listen
        case .match: match
        case .build: build
        case .find: find
        case .row: row
        case .say: say
        case .roleplay:
            RoleplayView(text: text, drill: drill, seed: seed, revealAll: revealRoleplay) { outcome in
                roleplayDone = outcome
                onFinish(outcome)
            }
        case nil: EmptyView()
        }
    }

    private var sentence: Sentence? { text.sentence(drill.sentence) }
    private var sentenceText: String { sentence?.text ?? "" }
    private var hasGap: Bool { drill.before != nil && drill.after != nil }

    /// The sentence: with its gap (blank while answering), or whole with the word to look at marked.
    private func stimulus(filled: String?) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Group {
                if hasGap {
                    Text(PracticeText.gapped(before: drill.before ?? "", filled: filled, after: drill.after ?? ""))
                } else {
                    Text(PracticeText.highlighted(sentenceText, range: drill.focus))
                }
            }
            .font(.system(.title2, design: .serif))
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityIdentifier("practice.sentence")
            if let cue = drill.cue, drill.strandKind != .verbs || hasGap {
                cueText(cue)
            }
            if let translation = sentence?.translation, drill.recipe != "word-recall" || isDone {
                Text(translation).font(.footnote).foregroundStyle(.secondary)
            }
        }
    }

    /// A gap's cue: the infinitive and person, or for a word-recall drill its English meaning.
    @ViewBuilder private func cueText(_ cue: String) -> some View {
        if drill.strandKind == .words && drill.format != .choice {
            Text("(\(cue))").font(.callout).foregroundStyle(.secondary)
        } else if drill.format != .choice || drill.strandKind == .grammar {
            Text(target: "(\(cue))").font(.callout).foregroundStyle(.secondary)
        }
    }

    // MARK: Choice

    private var choice: some View {
        let options = SeededShuffle.shuffled(drill.options ?? [], seed: seed)
        let english = drill.englishOptions
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
                            if english {
                                Text(option).font(.body)
                            } else {
                                Text(target: option).font(.system(.title3, design: .serif))
                            }
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

    // MARK: Gap and listen

    private var gap: some View {
        VStack(alignment: .leading, spacing: 14) {
            stimulus(filled: feedback.isDone ? (feedback.outcome == .shown ? drill.answer : typedOrAnswer) : nil)
            answerField
        }
    }

    private var listen: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                Button {
                    model.speech.say(drill.speak ?? drill.answer)
                } label: {
                    Image(systemName: "speaker.wave.2.fill")
                        .font(.title2)
                        .frame(width: 56, height: 56)
                        .foregroundStyle(Theme.background)
                        .background(Theme.ink, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Play the word")
                .accessibilityIdentifier("practice.play")
                Button("Slower") { model.speech.say(drill.speak ?? drill.answer, slow: true) }
                    .buttonStyle(.bordered)
                    .frame(minHeight: 44)
                Spacer()
            }
            .padding(12)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 14))
            stimulus(filled: feedback.isDone ? drill.answer : nil)
            answerField
        }
    }

    private var answerField: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField("Type in \(TargetLanguage.current.name)", text: $typed)
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
                .targetLanguage()
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

    // MARK: Say

    private var say: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let cue = drill.cue {
                Text(cue).font(.system(.title2, design: .serif)).italic()
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let label = drill.label {
                Text(label).font(.footnote).foregroundStyle(.secondary)
            }
            answerField
        }
    }

    // MARK: Build

    private var tileBank: [String] {
        SeededShuffle.tileBank(tiles: drill.tiles ?? [], distractors: drill.distractors ?? [], seed: seed)
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
        let right = SeededShuffle.shuffled(pairs.map { $0[1] }, seed: seed, avoidingGivenOrder: true)
        let english = drill.englishOptions
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
                    MatchTile(title: item, state: done ? .matched : badPair.last == item ? .wrong : .idle,
                              english: english) {
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

    // MARK: Find

    private var find: some View {
        let targets = Set(drill.targets ?? [])
        return VStack(alignment: .leading, spacing: 14) {
            ForEach(drill.sentences ?? [], id: \.self) { sid in
                if let s = text.sentence(sid) {
                    FlowLayout(spacing: 2) {
                        ForEach(Array(s.tokens.enumerated()), id: \.offset) { n, token in
                            let target = DrillTarget(s: sid, t: n)
                            if token.isWord {
                                FindToken(title: token.t, look: findLook(target, targets: targets)) {
                                    if picked.contains(target) { picked.remove(target) } else { picked.insert(target) }
                                    clearHint()
                                }
                                .disabled(feedback.isDone)
                            } else {
                                Text(token.t).font(.system(.title3, design: .serif)).padding(.vertical, 8)
                            }
                        }
                    }
                    .targetLanguage()
                }
            }
            Text("\(picked.count) picked").font(.footnote).foregroundStyle(.secondary)
        }
    }

    private func findLook(_ target: DrillTarget, targets: Set<DrillTarget>) -> FindToken.Look {
        let isPicked = picked.contains(target)
        guard feedback.isDone else { return isPicked ? .selected : .idle }
        if targets.contains(target) { return isPicked ? .right : .missed }
        return isPicked ? .wrong : .idle
    }

    // MARK: Row

    private var row: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(PracticeText.highlighted(sentenceText, range: drill.focus))
                .font(.system(.title3, design: .serif))
                .fixedSize(horizontal: false, vertical: true)
            VStack(spacing: 0) {
                ForEach(Array((drill.cells ?? []).enumerated()), id: \.offset) { n, cell in
                    if n > 0 { Divider() }
                    HStack(spacing: 12) {
                        Text(target: cell.label).font(.subheadline).foregroundStyle(.secondary)
                            .frame(width: 82, alignment: .leading)
                        if cell.given || feedback.outcome == .shown {
                            Text(target: cell.forms.first ?? "").font(.system(.title3, design: .serif))
                                .foregroundStyle(cell.given ? Theme.ink : Theme.error.foreground)
                            Spacer()
                        } else {
                            TextField(cell.label, text: Binding(get: { cells[cell.p] ?? "" },
                                                                set: { cells[cell.p] = $0; wrongCells.remove(cell.p) }))
                                .font(.system(.title3, design: .serif))
                                .autocorrectionDisabled()
                                #if os(iOS)
                                .textInputAutocapitalization(.never)
                                #endif
                                .focused($focusedCell, equals: cell.p)
                                .padding(.horizontal, 10)
                                .frame(minHeight: 44)
                                .background(RoundedRectangle(cornerRadius: 10)
                                    .stroke(wrongCells.contains(cell.p) ? Theme.error.foreground
                                            : feedback.isDone ? Theme.addedBorder : Theme.borderInput, lineWidth: 1.5))
                                .disabled(feedback.isDone)
                                .onSubmit { nextCell(after: cell.p) }
                                .targetLanguage()
                                .accessibilityIdentifier("practice.cell.\(cell.p)")
                        }
                    }
                    .padding(.vertical, 6)
                }
            }
            .padding(.horizontal, 12)
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.hairline))
            if !feedback.isDone {
                AccentKeys { key in
                    if let p = focusedCell { cells[p, default: ""] += key }
                }
            }
        }
        .onAppear { focusedCell = drill.cells?.first { !$0.given }?.p }
    }

    private var blankCells: [RowCell] { (drill.cells ?? []).filter { !$0.given } }

    private func nextCell(after p: String) {
        let blanks = blankCells.map(\.p)
        if let i = blanks.firstIndex(of: p), i + 1 < blanks.count {
            focusedCell = blanks[i + 1]
        } else {
            check()
        }
    }

    // MARK: Actions

    private var canCheck: Bool {
        switch drill.format {
        case .gap, .listen, .say: !typed.trimmingCharacters(in: .whitespaces).isEmpty
        case .build: !built.isEmpty
        case .find: !picked.isEmpty
        case .row: blankCells.allSatisfy { !(cells[$0.p] ?? "").trimmingCharacters(in: .whitespaces).isEmpty }
        default: false
        }
    }

    private var actions: some View {
        VStack(spacing: 4) {
            if isDone {
                Button(number == total ? "See how it went" : "Continue", action: onContinue)
                    .buttonStyle(PrimaryButtonStyle())
                    .keyboardShortcut(.defaultAction)
                    .accessibilityIdentifier("practice.continue")
            } else {
                if [.gap, .listen, .say, .build, .find, .row].contains(drill.format) {
                    Button("Check", action: check)
                        .buttonStyle(PrimaryButtonStyle())
                        .keyboardShortcut(.defaultAction)
                        .disabled(!canCheck)
                        .accessibilityIdentifier("practice.check")
                }
                HStack {
                    if let hint = drill.hint, !feedback.sawHint, drill.format != .roleplay {
                        Button("Show a hint") {
                            feedback.showHint()
                            panel = Panel(kind: .hint, headline: "Hint", detail: hint)
                        }
                        .accessibilityIdentifier("practice.hint")
                        Spacer()
                    }
                    Button(drill.format == .roleplay ? "Show the conversation" : "Show answer", action: reveal)
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
        guard !feedback.isDone, canCheck else { return }
        let grade: Grade
        switch drill.format {
        case .gap, .listen:
            grade = DrillGrader.grade(typed, for: drill)
        case .say:
            grade = PatternGrader.grade(typed, patterns: (drill.accept ?? []) + (drill.answers ?? []), german: drill.isGerman)
        case .build:
            let bank = tileBank
            grade = DrillGrader.grade(tiles: built.map { bank[$0] }, for: drill)
        case .find:
            grade = DrillGrader.grade(selection: picked, for: drill)
        case .row:
            var wrong: Set<String> = []
            for cell in blankCells {
                switch DrillGrader.grade(cells[cell.p] ?? "", cell: cell, for: drill) {
                case .wrong: wrong.insert(cell.p)
                case .accentSlip(let expected): cells[cell.p] = expected
                case .correct: break
                }
            }
            wrongCells = wrong
            grade = wrong.isEmpty ? .correct
                : .wrong(hint: wrong.count == 1 ? "Check the cell in red." : "Check the \(wrong.count) cells in red.")
        default:
            return
        }
        switch grade {
        case .correct:
            feedback.record(accepted: true)
            succeed(accentSlip: nil)
        case .accentSlip(let expected):
            feedback.record(accepted: true)
            if drill.format != .row { typed = expected }
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
        if drill.format == .roleplay {
            revealRoleplay = true
            return
        }
        feedback.reveal()
        if drill.format == .match {
            for pair in drill.pairs ?? [] where pair.count == 2 { matched[pair[0]] = pair[1] }
        }
        showAnswerPanel()
    }

    private func succeed(accentSlip: String?) {
        let headline = accentSlip.map { "Yes. Watch the accent: \($0)." } ?? (feedback.outcome == .firstTry ? "Yes." : "That's it.")
        panel = Panel(kind: .success, headline: headline, detail: drill.format == .say ? nil : drill.rule,
                      also: drill.also ?? [])
        finish()
    }

    private func showAnswerPanel() {
        let answer: String
        switch drill.format {
        case .match: answer = (drill.pairs ?? []).filter { $0.count == 2 }.map { "\($0[0]) → \($0[1])" }.joined(separator: ", ")
        case .find, .row: answer = drill.rule ?? ""
        case .say: answer = drill.answer
        default: answer = hasGap || drill.format == .choice && drill.strandKind == .grammar ? sentenceText : drill.answer
        }
        panel = Panel(kind: .shown, headline: "Here's the answer.", detail: answer, also: drill.also ?? [])
        finish()
    }

    private func finish() {
        fieldFocused = false
        focusedCell = nil
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
                    if drill.englishOptions && drill.format == .choice && !hasGap {
                        Text(detail).font(.body)
                    } else {
                        Text(target: detail).font(.system(.body, design: .serif))
                    }
                    if let rule = drill.rule, ![.build, .find, .row, .say].contains(drill.format) {
                        Text(markdown: rule).font(.callout)
                    }
                } else {
                    Text(markdown: detail).font(.callout)
                }
            }
            if !panel.also.isEmpty && panel.kind != .hint {
                Text("You could also say").font(.footnote.weight(.semibold)).padding(.top, 4)
                ForEach(panel.also, id: \.self) { line in
                    Text(target: line).font(.system(.callout, design: .serif))
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

/// The target language's accent keys (à è é ì ò ù for Italian), appended to the answer.
struct AccentKeys: View {
    let insert: (String) -> Void

    var body: some View {
        HStack(spacing: 6) {
            ForEach(TargetLanguage.current.accentKeys, id: \.self) { c in
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
            Text(target: title)
                .font(.system(.title3, design: .serif))
                .padding(.horizontal, 12)
                .frame(minHeight: 44)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.hairline))
        }
        .buttonStyle(.plain)
    }
}

/// A word of a `find` drill's lines.
struct FindToken: View {
    enum Look { case idle, selected, right, wrong, missed }
    let title: String
    let look: Look
    let action: () -> Void

    var body: some View {
        let colors: (Color, Color) = switch look {
        case .idle: (Color.clear, Theme.ink)
        case .selected: (Theme.selectionFill, Theme.accent)
        case .right: (Theme.added.background, Theme.added.foreground)
        case .wrong: (Theme.error.background, Theme.error.foreground)
        case .missed: (Color.clear, Theme.added.foreground)
        }
        Button(action: action) {
            Text(title)
                .font(.system(.title3, design: .serif).weight(look == .idle ? .regular : .semibold))
                .underline(look == .missed)
                .padding(.horizontal, 3)
                .frame(minHeight: 44)
                .foregroundStyle(colors.1)
                .background(colors.0, in: RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(look == .selected ? .isSelected : [])
        .accessibilityValue(value)
    }

    private var value: String {
        switch look {
        case .idle: ""
        case .selected: "Picked"
        case .right: "Right"
        case .wrong: "Not one"
        case .missed: "Missed"
        }
    }
}

struct MatchTile: View {
    enum Look { case idle, selected, matched, wrong }
    let title: String
    let state: Look
    var english = false
    let action: () -> Void

    var body: some View {
        let colors: (Color, Color, Color) = switch state {
        case .idle: (Theme.background, Theme.ink, Theme.hairline)
        case .selected: (Theme.selectionFill, Theme.ink, Theme.accent)
        case .matched: (Theme.added.background, Theme.added.foreground, Theme.addedBorder)
        case .wrong: (Theme.error.background, Theme.error.foreground, Theme.error.foreground)
        }
        Button(action: action) {
            Group {
                if english {
                    Text(title).font(.subheadline)
                } else {
                    Text(target: title).font(.system(.body, design: .serif))
                }
            }
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
