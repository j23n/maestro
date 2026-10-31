import SwiftData
import SwiftUI
import ItalianCore
import PackKit

/// The reader (HANDOFF.md 3.1): clean serif text, nothing highlighted but the current selection.
/// Tapping a word opens help.
struct ReaderView: View {
    let textID: String

    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @Environment(\.modelContext) private var context
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var selection: TokenSelection?
    @State private var help: HelpContent?
    @State private var showHelp = false
    @State private var fraction: Double = 0

    var body: some View {
        if let text = model.text(textID) {
            reader(text)
        } else {
            EmptyState(title: "Text not available", message: "This text isn't in the packs on this device.",
                       systemImage: "doc.questionmark")
        }
    }

    private func reader(_ text: ReadingText) -> some View {
        let starts = Self.blockStarts(text)
        let highlighted = Set(help?.tokenIndices ?? [])
        let spoken = spokenSentence(text)
        let size = Theme.readingSize(regular: sizeClass == .regular, scale: prefs.textScale)
        return ScrollView {
            VStack(alignment: .leading, spacing: size * 0.9) {
                header(text)
                ForEach(Array(text.blocks.enumerated()), id: \.offset) { i, block in
                    BlockView(block: block, startIndex: starts[i], selection: selection, highlighted: highlighted,
                              spokenSentence: spoken, size: size)
                }
                footer(text)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 16)
            .frame(maxWidth: 720, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .onScrollGeometryChange(for: Double.self) { geo in
            let scrollable = geo.contentSize.height - geo.containerSize.height
            guard scrollable > 0 else { return 1 }
            return min(1, max(0, (geo.contentOffset.y + geo.contentInsets.top) / scrollable))
        } action: { _, new in
            fraction = new
        }
        .environment(\.openURL, OpenURLAction { url in
            open(url, in: text)
            return .handled
        })
        .inspector(isPresented: $showHelp) {
            NavigationStack {
                if let help {
                    HelpView(help: help).withRoutes()
                }
            }
            .presentationDetents([.medium, .large])
            .inspectorColumnWidth(min: 300, ideal: 360, max: 440)
        }
        .onChange(of: showHelp) { _, shown in
            if !shown {
                selection = nil
                help = nil
            }
        }
        .navigationTitle(text.title)
        #if DEBUG
        .task {
            if let t = UITestLaunch.token(in: text), let url = URL(string: "maestro-token://t/\(t.sentence)/\(t.token)") {
                open(url, in: text)
            }
        }
        #endif
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .toolbar { toolbar(text) }
        .onDisappear { saveProgress() }
    }

    // MARK: Pieces

    private func header(_ text: ReadingText) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(italian: text.title)
                .font(.system(size: 28, weight: .bold, design: .serif))
            HStack(spacing: 6) {
                LevelTag(level: text.level)
                Text("\(collectionTitle(text)) · \(text.wordCount) words")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.bottom, 4)
    }

    private func footer(_ text: ReadingText) -> some View {
        VStack(spacing: 12) {
            Divider().padding(.vertical, 8)
            if !text.questions.isEmpty {
                NavigationLink(value: Route.questions(text.id)) {
                    Label("Questions (\(text.questions.count))", systemImage: "questionmark.bubble")
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.borderedProminent)
            }
            Button {
                RememberStore(context: context, prefs: prefs, content: model.content).updateProgress(textID: textID, position: 1)
            } label: {
                Label("Mark as read", systemImage: "checkmark")
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.bordered)
        }
    }

    @ToolbarContentBuilder
    private func toolbar(_ text: ReadingText) -> some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            Button {
                readAloud(text)
            } label: {
                Image(systemName: isPlayingThis(text) ? "pause.circle" : "play.circle")
            }
            .accessibilityLabel(isPlayingThis(text) ? "Pause reading aloud" : "Read aloud")

            Menu {
                Picker("Text size", selection: Bindable(prefs).textScale) {
                    Text("Small").tag(0.85)
                    Text("Default").tag(1.0)
                    Text("Large").tag(1.15)
                    Text("Larger").tag(1.3)
                    Text("Largest").tag(1.5)
                }
            } label: {
                Image(systemName: "textformat.size")
            }
            .accessibilityLabel("Text size")

            if sizeClass == .regular && !text.questions.isEmpty {
                NavigationLink(value: Route.questions(text.id)) {
                    Image(systemName: "questionmark.bubble")
                }
                .accessibilityLabel("Questions")
            }
        }
    }

    // MARK: Actions

    private func open(_ url: URL, in text: ReadingText) {
        let parts = url.pathComponents.filter { $0 != "/" }.compactMap(Int.init)
        guard url.scheme == "maestro-token", parts.count == 2 else { return }
        let sentences = text.sentences
        guard sentences.indices.contains(parts[0]), sentences[parts[0]].tokens.indices.contains(parts[1]) else { return }
        let sel = TokenSelection(sentenceIndex: parts[0], tokenIndex: parts[1])
        selection = sel
        help = HelpContent(text: text, sentence: sentences[parts[0]], tokenIndex: parts[1], content: model.content)
        showHelp = true
    }

    private func saveProgress() {
        guard fraction > 0.02 else { return }
        let store = RememberStore(context: context, prefs: prefs, content: model.content)
        let previous = store.progress(for: textID)?.position ?? 0
        if previous < 1 || fraction > previous {
            store.updateProgress(textID: textID, position: fraction)
        }
    }

    private func readAloud(_ text: ReadingText) {
        let speech = model.speech
        if isPlayingThis(text) {
            speech.pause()
            return
        }
        if speech.segments.first?.id.hasPrefix("\(text.id)#") == true {
            speech.play()
            return
        }
        speech.rate = prefs.speechRate
        speech.load(Self.segments(text))
        speech.play()
    }

    private func isPlayingThis(_ text: ReadingText) -> Bool {
        model.speech.isPlaying && model.speech.currentSegment?.id.hasPrefix("\(text.id)#") == true
    }

    private func spokenSentence(_ text: ReadingText) -> Int? {
        guard model.speech.isPlaying, let id = model.speech.currentSegment?.id,
              id.hasPrefix("\(text.id)#") else { return nil }
        return Int(id.dropFirst(text.id.count + 1))
    }

    private func collectionTitle(_ text: ReadingText) -> String {
        model.library.entry(for: text.id)?.pack.manifest.title ?? text.collection
    }

    /// Speech segments for a text: one per sentence, IDs "<textID>#<global sentence index>".
    static func segments(_ text: ReadingText) -> [SpeechSegment] {
        var out: [SpeechSegment] = []
        for block in text.blocks {
            for sentence in block.sentences {
                out.append(SpeechSegment(id: "\(text.id)#\(out.count)", text: sentence.text,
                                         speaker: block.type == .dialogue ? block.speaker : nil))
            }
        }
        return out
    }

    /// The global index of each block's first sentence.
    static func blockStarts(_ text: ReadingText) -> [Int] {
        var starts: [Int] = []
        var n = 0
        for block in text.blocks {
            starts.append(n)
            n += block.sentences.count
        }
        return starts
    }
}

/// One block of text, every word a link that opens help.
struct BlockView: View {
    let block: Block
    let startIndex: Int
    let selection: TokenSelection?
    let highlighted: Set<Int>
    let spokenSentence: Int?
    let size: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            if block.type == .dialogue, let speaker = block.speaker {
                Text(italian: speaker)
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            Text(attributed)
                .font(Theme.readingFont(size: size))
                .lineSpacing(size * 0.45)
                .tint(Theme.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.leading, block.type == .verse || block.type == .sign ? 16 : 0)
        }
    }

    private var attributed: AttributedString {
        var a = AttributedString(block.text)
        a.languageIdentifier = "it-IT"
        for (j, sentence) in block.sentences.enumerated() {
            let si = startIndex + j
            if spokenSentence == si,
               let r = Range(NSRange(location: sentence.r.start, length: sentence.r.length), in: a) {
                a[r].backgroundColor = Theme.surface
            }
            for (k, token) in sentence.tokens.enumerated() where token.isWord {
                let ns = NSRange(location: sentence.r.start + token.r.start, length: token.r.length)
                guard let r = Range(ns, in: a) else { continue }
                a[r].link = URL(string: "maestro-token://t/\(si)/\(k)")
                if selection?.sentenceIndex == si && highlighted.contains(k) {
                    a[r].backgroundColor = Theme.selectionFill
                }
            }
        }
        return a
    }
}
