import SwiftUI
import PackKit

/// The player (HANDOFF.md 3.6): Show text / Listen first, the current sentence and word
/// highlighted, scrubber by sentence, previous / play-pause / next, speed, repeat.
struct PlayerView: View {
    let textID: String
    var listenFirst = false

    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @State private var showText = true

    private var speech: SpeechPlayer { model.speech }

    var body: some View {
        if let text = model.text(textID) {
            VStack(spacing: 0) {
                Picker("Mode", selection: $showText) {
                    Text("Show text").tag(true)
                    Text("Listen first").tag(false)
                }
                .pickerStyle(.segmented)
                .padding()
                if showText {
                    transcript(text)
                } else {
                    VStack(spacing: 12) {
                        Spacer()
                        Image(systemName: "ear").font(.system(size: 54)).foregroundStyle(.secondary)
                        Text("Listen without the text first, then switch to Show text.")
                            .multilineTextAlignment(.center)
                            .foregroundStyle(.secondary)
                        Spacer()
                    }
                    .padding()
                }
                controls
            }
            .navigationTitle(text.title)
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .onAppear { prepare(text) }
        } else {
            EmptyState(title: "Text not available", message: "", systemImage: "doc.questionmark")
        }
    }

    private func prepare(_ text: ReadingText) {
        showText = !listenFirst
        let segments = ReaderView.segments(text)
        if speech.segments.first?.id != segments.first?.id {
            speech.rate = prefs.speechRate
            speech.load(segments)
        }
    }

    private func transcript(_ text: ReadingText) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(Array(speech.segments.enumerated()), id: \.element.id) { i, segment in
                        Text(sentence(segment, current: i == speech.index))
                            .font(.system(size: 20, design: .serif))
                            .lineSpacing(6)
                            .foregroundStyle(i == speech.index ? Theme.ink : Color.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                            .onTapGesture { speech.jump(to: i) }
                            .id(i)
                    }
                }
                .padding(20)
                .frame(maxWidth: 720)
                .frame(maxWidth: .infinity)
            }
            .onChange(of: speech.index) { _, i in
                withAnimation { proxy.scrollTo(i, anchor: .center) }
            }
        }
    }

    private func sentence(_ segment: SpeechSegment, current: Bool) -> AttributedString {
        var a = AttributedString(segment.text)
        a.languageIdentifier = "it-IT"
        if current, let word = speech.wordRange, let r = Range(word, in: a) {
            a[r].backgroundColor = Theme.selectionFill
        }
        return a
    }

    private var controls: some View {
        VStack(spacing: 12) {
            if speech.segments.count > 1 {
                Slider(value: Binding(get: { Double(speech.index) },
                                      set: { speech.jump(to: Int($0.rounded())) }),
                       in: 0...Double(speech.segments.count - 1), step: 1)
                    .accessibilityLabel("Sentence")
                    .accessibilityValue("\(speech.index + 1) of \(speech.segments.count)")
            }
            Text("Sentence \(speech.index + 1) of \(max(1, speech.segments.count))")
                .font(.caption).monospacedDigit().foregroundStyle(.secondary)
            HStack(spacing: 36) {
                Button { speech.previous() } label: {
                    Image(systemName: "backward.end.fill").font(.title2).frame(width: 44, height: 44)
                }
                .accessibilityLabel("Previous sentence")
                Button { speech.toggle() } label: {
                    Image(systemName: speech.isPlaying ? "pause.circle.fill" : "play.circle.fill")
                        .font(.system(size: 56))
                }
                .accessibilityLabel(speech.isPlaying ? "Pause" : "Play")
                Button { speech.next() } label: {
                    Image(systemName: "forward.end.fill").font(.title2).frame(width: 44, height: 44)
                }
                .accessibilityLabel("Next sentence")
            }
            .buttonStyle(.plain)
            HStack {
                Menu {
                    Picker("Speed", selection: Binding(get: { prefs.speechRate }, set: { rate in
                        prefs.speechRate = rate
                        speech.rate = rate
                    })) {
                        Text("0.6×").tag(0.6)
                        Text("0.7×").tag(0.7)
                        Text("0.8×").tag(0.8)
                        Text("0.9×").tag(0.9)
                        Text("1×").tag(1.0)
                    }
                } label: {
                    Label(String(format: "%.1f×", prefs.speechRate), systemImage: "speedometer")
                }
                Spacer()
                Toggle(isOn: Binding(get: { speech.repeatEach }, set: { speech.repeatEach = $0 })) {
                    Label("Repeat each sentence", systemImage: "repeat.1")
                }
                .toggleStyle(.button)
            }
            .font(.subheadline)
        }
        .padding()
        .background(.bar)
    }
}
