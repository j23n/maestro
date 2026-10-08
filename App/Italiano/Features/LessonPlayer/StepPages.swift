import LearningCore
import SwiftUI

// The non-exercise pages of a lesson (docs/06 §§ 1–5, 16, Opener; `Main.png`, `Grammar.png`). Exercises are drawn
// by ExerciseHostView; LessonPlayerView puts either between the chrome.

/// What every page needs from the player.
@MainActor
struct PlayerServices {
    let audio: ExerciseAudio
    let speech: SpeechCapture
    /// `glossTapped` (docs/05 § Events): text, 1-based line, token index, item.
    var onGloss: (TextID, Int, Int, ItemID?) -> Void = { _, _, _, _ in }
}

// MARK: - Opener

struct OpenerPage: View {
    let bundle: LessonBundle
    let onContinue: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
            Spacer()
            Mascot(pose: .hello, size: 96, decorative: true)
            ItalianText(bundle.title, style: Tokens.TypeScale.unitTitle)
            Spacer()
            Button("Start", action: onContinue)
                .buttonStyle(.dsPrimary)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("opener.continue")
        }
        .readableColumn()
    }
}

// MARK: - Preview: meet cards

struct MeetPage: View {
    let words: [WordInfo]
    let services: PlayerServices
    let onContinue: () -> Void
    @State private var index = 0

    var body: some View {
        VStack(spacing: Tokens.Space.xxl) {
            ExerciseInstruction("New words \(min(index + 1, words.count)) of \(words.count)")
            Spacer()
            if let word = words[safe: index] {
                Button {
                    services.audio.play(word.audioID, context: .item)
                } label: {
                    card(word)
                }
                .buttonStyle(.plain)
                .accessibilityHint(Text("Plays the word again"))
                .accessibilityIdentifier("preview.card")
                .reviewCommentable(ReviewTargets.word(word))
            }
            Spacer()
            Button(index + 1 < words.count ? "Next" : "Continue") {
                if index + 1 < words.count { index += 1 } else { onContinue() }
            }
            .buttonStyle(.dsPrimary)
            .keyboardShortcut(.return, modifiers: [])
            .accessibilityIdentifier("preview.next")
        }
        .readableColumn()
        .onAppear { playCurrent() }
        .onChange(of: index) { _, _ in playCurrent() }
    }

    private func card(_ w: WordInfo) -> some View {
        Card {
            VStack(spacing: Tokens.Space.m) {
                ItalianText(
                    w.display,
                    style: TypeStyle(
                        family: .italian, size: 34, weight: 600, lineHeight: nil,
                        italic: false, relativeTo: .largeTitle))
                Text("\(w.partOfSpeech) · \(w.gloss)").dsFont(Tokens.TypeScale.uiCallout)
                    .foregroundStyle(Color.ds.secondary)
                if let note = w.note { MixedText(text: note, style: Tokens.TypeScale.uiBody) }
                if services.audio.canPlay(w.audioID) {
                    Image(systemName: "speaker.wave.2").foregroundStyle(Color.ds.accent).accessibilityHidden(true)
                }
            }
            .frame(maxWidth: .infinity)
        }
    }

    /// docs/06 §1: each card's audio plays once automatically.
    private func playCurrent() {
        if let w = words[safe: index] { services.audio.play(w.audioID, context: .item) }
    }
}

// MARK: - Story

struct StoryPage: View {
    let text: PlayerText
    let bundle: LessonBundle
    let services: PlayerServices
    let onContinue: () -> Void
    @Environment(\.isCompactWidth) private var isCompact
    @State private var selection: TokenPosition?
    @State private var rate = 1.0
    @State private var showEnglish = false
    @State private var showSpeakers = true

    var body: some View {
        VStack(spacing: 0) {
            if isCompact {
                lines
                    .sheet(item: sheetBinding) { pick in
                        panel(for: pick.position).padding(Tokens.Space.xxl).presentationDetents([.medium])
                    }
            } else {
                HStack(alignment: .top, spacing: 0) {
                    lines
                    Divider()
                    ScrollView {
                        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                            if let selection { panel(for: selection) }
                            newWords
                        }
                        .padding(Tokens.Space.xxl)
                    }
                    .frame(width: 340)
                }
            }
            Divider()
            audioBar
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    Toggle("English under each line", isOn: $showEnglish)
                    Toggle("Speaker names", isOn: $showSpeakers)
                } label: {
                    Text("Aa").dsFont(Tokens.TypeScale.uiTitle)
                }
                .accessibilityLabel(Text("Text options"))
                .accessibilityIdentifier("story.textSize")
            }
        }
        .showEnglishMenu($showEnglish)
    }

    private var lines: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Tokens.Space.l) {
                ForEach(Array(text.lines.enumerated()), id: \.element.number) { n, line in
                    VStack(alignment: .leading, spacing: Tokens.Space.xs) {
                        if showSpeakers, let speaker = line.speaker,
                            n == 0 || text.lines[n - 1].speaker != speaker
                        {
                            Text((bundle.characters[speaker] ?? "").uppercased())
                                .dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.secondary)
                        }
                        TokenText(
                            text: line.text, line: line.number,
                            style: isCompact ? Tokens.TypeScale.storyCompact : Tokens.TypeScale.storyRegular,
                            current: readAlong(line.number),
                            selected: selection?.line == line.number ? selection?.index : nil,
                            marksNewWords: true, onTap: { tap(line: line.number, token: $0) })
                        if showEnglish, let en = line.english {
                            Text(en).dsFont(Tokens.TypeScale.translation).foregroundStyle(Color.ds.secondary)
                        }
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityAction(named: Text("Play line")) {
                        services.audio.play(text.audioID, fromLine: line.number, rate: rate)
                    }
                    .accessibilityAction(named: Text("Show English")) { showEnglish = true }
                    .reviewCommentable(ReviewTargets.line(text, line))
                }
            }
            .frame(maxWidth: Tokens.Size.readableWidth, alignment: .leading)
            .padding(isCompact ? Tokens.Space.screenPaddingCompact : Tokens.Space.screenPaddingRegular)
        }
        .accessibilityIdentifier("story.text")
    }

    @ViewBuilder private func panel(for position: TokenPosition) -> some View {
        if let g = bundle.gloss(text: text.id, line: position.line, token: position.index) {
            WordPanel(
                headword: g.headword, posAndGloss: g.posAndGloss, note: g.note,
                canPlay: services.audio.canPlay(g.audioID),
                hearIt: { services.audio.play(g.audioID, context: .item) })
        }
    }

    private var newWords: some View {
        let words = bundle.newWords(in: text.id)
        return VStack(alignment: .leading, spacing: Tokens.Space.m) {
            if !words.isEmpty {
                Text("New in this story").dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                ForEach(words, id: \.itemID) { w in
                    HStack(alignment: .firstTextBaseline) {
                        ItalianText(w.display, style: Tokens.TypeScale.rowTitle)
                        Spacer()
                        Text(w.gloss).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                    }
                    .reviewCommentable(ReviewTargets.word(w))
                    Divider()
                }
            }
        }
    }

    private var audioBar: some View {
        let p = services.audio.player
        let mine = services.audio.current == text.audioID && text.audioID != nil
        return AudioBar(
            isPlaying: mine && p.isPlaying,
            progress: mine && p.durationMs > 0 ? Double(p.positionMs) / Double(p.durationMs) : 0,
            timeText: mine ? PlaybackClock.position(p.positionMs, of: p.durationMs) : "",
            rateText: PlaybackClock.rate(rate),
            togglePlay: togglePlay,
            cycleRate: {
                let choices = PlaybackRate.storyChoices
                rate = rate == choices[0] ? choices[1] : choices[0]
                if mine { p.setRate(rate) }
            },
            seek: { fraction in if mine { p.seek(toMs: Int(fraction * Double(p.durationMs))) } }
        ) {
            Button("Continue to practice", action: onContinue)
                .buttonStyle(.dsSecondary)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("story.continue")
        }
    }

    private func togglePlay() {
        let p = services.audio.player
        if services.audio.current == text.audioID, p.isPlaying {
            p.pause()
        } else if services.audio.current == text.audioID, p.positionMs > 0, p.positionMs < p.durationMs {
            p.resume()
        } else {
            services.audio.play(text.audioID, rate: rate, context: .story)
        }
    }

    private func readAlong(_ line: Int) -> Int? {
        guard services.audio.isPlaying(text.audioID), let t = services.audio.player.currentToken, t.line == line
        else { return nil }
        return t.index
    }

    private func tap(line: Int, token: Int) {
        selection = TokenPosition(line: line, index: token)
        let item = text.lines.first { $0.number == line }?.text.tokens[safe: token]?.itemId
        services.onGloss(text.id, line, token, item)
    }

    private struct SheetPick: Identifiable {
        let position: TokenPosition
        var id: TokenPosition { position }
    }

    private var sheetBinding: Binding<SheetPick?> {
        Binding(get: { selection.map(SheetPick.init) }, set: { selection = $0?.position })
    }
}

// MARK: - Listening and its transcript

struct ListeningPage: View {
    let text: PlayerText
    let plays: Int?
    let services: PlayerServices
    let onContinue: () -> Void

    var body: some View {
        VStack(spacing: Tokens.Space.xxl) {
            Spacer()
            ExerciseInstruction("Listen. You'll answer questions next.")
            BigPlayButton(
                isPlaying: services.audio.isPlaying(text.audioID), action: { play(rate: 1) },
                identifier: "listening.play"
            )
            .disabled(!canPlay && !services.audio.isPlaying(text.audioID))
            Button("Play slower") { play(rate: PlaybackRate.slower) }
                .buttonStyle(.dsSecondarySmall)
                .disabled(!canPlay)
                .accessibilityIdentifier("listening.slower")
            Text(counter).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                .accessibilityIdentifier("listening.count")
            Spacer()
            Button("Continue to questions", action: onContinue)
                .buttonStyle(.dsPrimary)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("feedback.continue")
        }
        .readableColumn()
    }

    private var used: Int { services.audio.plays(of: text.audioID) }
    private var canPlay: Bool { services.audio.canPlay(text.audioID) && (plays.map { used < $0 } ?? true) }

    private var counter: String {
        if let plays { return "Played \(used) of \(plays)" }
        return used == 1 ? "Played once" : "Played \(used) times"
    }

    private func play(rate: Double) {
        if services.audio.isPlaying(text.audioID) {
            services.audio.stop()
        } else if canPlay {
            services.audio.play(text.audioID, rate: rate, context: .story)
        }
    }
}

struct TranscriptPage: View {
    let text: PlayerText
    let bundle: LessonBundle
    let services: PlayerServices
    let onContinue: () -> Void
    @State private var shown = false

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
            if shown {
                StoryPage(text: text, bundle: bundle, services: services, onContinue: onContinue)
            } else {
                Spacer()
                ExerciseInstruction("Want to see what was said?")
                Button("Show transcript") { shown = true }
                    .buttonStyle(.dsSecondary)
                    .accessibilityIdentifier("listening.transcript")
                Spacer()
                ContinueButton(action: onContinue)
            }
        }
        .readableColumn()
    }
}

// MARK: - Reading

struct ReadingPage: View {
    let text: PlayerText
    let services: PlayerServices
    let onContinue: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                ExerciseInstruction("Read it. Tap any word for its meaning.")
                if let layout = text.layout {
                    RealWorldLayoutView(
                        layout: layout,
                        onTap: { line, token in
                            services.onGloss(text.id, line, token, nil)
                        })
                } else {
                    Card {
                        VStack(alignment: .leading, spacing: Tokens.Space.s) {
                            ForEach(text.lines, id: \.number) { line in
                                TokenText(
                                    text: line.text, line: line.number,
                                    onTap: { token in
                                        services.onGloss(
                                            text.id, line.number, token,
                                            line.text.tokens[safe: token]?.itemId)
                                    })
                            }
                        }
                    }
                }
                ContinueButton(action: onContinue)
            }
            .readableColumn()
        }
    }
}

// MARK: - Grammar note

struct NotePage: View {
    let note: NoteBody
    let onContinue: () -> Void
    @Environment(\.isCompactWidth) private var isCompact

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                if let intro = note.intro {
                    HStack(alignment: .top, spacing: Tokens.Space.l) {
                        Mascot(
                            pose: Mascot.Pose(rawValue: intro.mascot) ?? .think, size: 72, decorative: true,
                            isHint: true)
                        MixedText(text: intro.textEn, style: Tokens.TypeScale.translation)
                            .foregroundStyle(Color.ds.secondary)
                    }
                }
                Text(MixedText.attributed(note.titleEn)).dsFont(Tokens.TypeScale.noteTitle)
                    .foregroundStyle(Color.ds.ink)
                    .accessibilityAddTraits(.isHeader)
                ForEach(Array(note.blocks.enumerated()), id: \.offset) { _, block in
                    blockView(block)
                }
                Button("Try it", action: onContinue)
                    .buttonStyle(.dsPrimary)
                    .keyboardShortcut(.return, modifiers: [])
                    .accessibilityIdentifier("note.tryIt")
            }
            .readableColumn()
        }
    }

    @ViewBuilder private func blockView(_ block: NoteBody.Block) -> some View {
        switch block {
        case .paragraph(let p):
            MixedText(text: p, style: Tokens.TypeScale.uiBody)
        case .table(let t):
            let layout =
                isCompact && t.columns.count > 2
                ? AnyLayout(VStackLayout(spacing: Tokens.Space.l))
                : AnyLayout(HStackLayout(alignment: .top, spacing: Tokens.Space.l))
            layout {
                ForEach(Array(t.columns.enumerated()), id: \.offset) { c, title in
                    Card {
                        VStack(alignment: .leading, spacing: Tokens.Space.s) {
                            Text(title).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                            ForEach(Array(t.rows.enumerated()), id: \.offset) { _, row in
                                if let cell = row[safe: c], !cell.isEmpty {
                                    ItalianText(cell, style: Tokens.TypeScale.italianBody)
                                }
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .accessibilityIdentifier("note.table")
        case .examples(let examples):
            VStack(alignment: .leading, spacing: Tokens.Space.l) {
                ForEach(Array(examples.enumerated()), id: \.offset) { n, e in
                    VStack(alignment: .leading, spacing: Tokens.Space.xs) {
                        TokenText(text: e.text, line: e.line, highlight: Set(e.highlight))
                        Text(e.en).dsFont(Tokens.TypeScale.translation).foregroundStyle(Color.ds.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("note.example.\(n)")
                }
            }
        case .tip(let tip):
            MixedText(text: "**Tip:** " + tip, style: Tokens.TypeScale.uiBody)
                .padding(Tokens.Space.xl)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: Tokens.Radius.tableCard).fill(Color.ds.surface))
        }
    }
}

// MARK: - Fluency replay

struct FluencyPage: View {
    let texts: [PlayerText]
    let rate: Double
    let services: PlayerServices
    let onDone: () -> Void
    @State private var index = 0
    @State private var fast = false

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: Tokens.Space.l) {
                    ExerciseInstruction("Listen at full speed. Tap a word if you need it.")
                    if let text = texts[safe: index] {
                        ForEach(text.lines, id: \.number) { line in
                            TokenText(
                                text: line.text, line: line.number, style: Tokens.TypeScale.storyCompact,
                                current: readAlong(text, line.number),
                                onTap: { token in
                                    services.onGloss(
                                        text.id, line.number, token,
                                        line.text.tokens[safe: token]?.itemId)
                                })
                        }
                    }
                }
                .readableColumn()
            }
            Divider()
            HStack(spacing: Tokens.Space.l) {
                BigPlayButton(isPlaying: playing, action: toggle, identifier: "fluency.play")
                    .scaleEffect(0.64)
                Button(PlaybackClock.rate(currentRate)) {
                    fast.toggle()
                    if playing { services.audio.player.setRate(currentRate) }
                }
                .buttonStyle(.dsSecondarySmall)
                .accessibilityIdentifier("fluency.speed")
                Spacer()
                Button("Done", action: onDone)
                    .buttonStyle(.dsPrimary)
                    .accessibilityIdentifier("fluency.done")
            }
            .padding(Tokens.Space.l)
        }
        .onChange(of: services.audio.player.isPlaying) { was, now in
            // One text ended: go on to the next one.
            if was, !now, services.audio.current == texts[safe: index]?.audioID, index + 1 < texts.count {
                index += 1
                services.audio.play(texts[index].audioID, rate: currentRate, context: .fluency)
            }
        }
    }

    private var currentRate: Double { fast ? 1.25 : rate }
    private var playing: Bool { services.audio.isPlaying(texts[safe: index]?.audioID) }

    private func toggle() {
        if playing {
            services.audio.stop()
        } else {
            services.audio.play(texts[safe: index]?.audioID, rate: currentRate, context: .fluency)
        }
    }

    private func readAlong(_ text: PlayerText, _ line: Int) -> Int? {
        guard services.audio.isPlaying(text.audioID), let t = services.audio.player.currentToken, t.line == line
        else { return nil }
        return t.index
    }
}

// MARK: - Check sections

struct CheckSectionPage: View {
    let title: String
    let onContinue: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
            Spacer()
            ExerciseInstruction("Unit check")
            Text(title).dsFont(Tokens.TypeScale.screenTitle).foregroundStyle(Color.ds.ink)
                .accessibilityAddTraits(.isHeader)
            Text("No hints in the check. Answer as well as you can; you'll see your results at the end.")
                .dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
            Spacer()
            Button("Start", action: onContinue)
                .buttonStyle(.dsPrimary)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("check.start")
        }
        .readableColumn()
    }
}
