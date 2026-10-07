import SwiftUI

/// 88 pt accent circle with a speaker glyph; pulses gently while playing (static with Reduce Motion).
struct BigPlayButton: View {
    let isPlaying: Bool
    let action: () -> Void
    var identifier = "dictation.play"
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pulse = false

    var body: some View {
        Button(action: action) {
            Image(systemName: isPlaying ? "speaker.wave.3.fill" : "speaker.wave.2.fill")
                .font(.system(size: 34, weight: .semibold))
                .foregroundStyle(Color.ds.onAccent)
                .frame(width: Tokens.Size.bigPlayButton, height: Tokens.Size.bigPlayButton)
                .background(Circle().fill(Color.ds.accent))
                .scaleEffect(isPlaying && pulse && !reduceMotion ? 1.06 : 1)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(isPlaying ? "Playing" : "Play"))
        .accessibilityIdentifier(identifier)
        .onChange(of: isPlaying) { _, playing in
            guard playing, !reduceMotion else { pulse = false; return }
            withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) { pulse = true }
        }
    }
}

/// Play button (56 circle), scrubber (accent fill), time, speed pill, and the primary action on the right.
struct AudioBar<Primary: View>: View {
    let isPlaying: Bool
    let progress: Double  // 0…1
    let timeText: String
    let rateText: String
    let togglePlay: () -> Void
    let cycleRate: () -> Void
    let seek: (Double) -> Void
    @ViewBuilder var primary: Primary

    var body: some View {
        HStack(spacing: Tokens.Space.l) {
            Button(action: togglePlay) {
                Image(systemName: isPlaying ? "pause.fill" : "play.fill")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(Color.ds.onAccent)
                    .frame(width: 56, height: 56)
                    .background(Circle().fill(Color.ds.accent))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text(isPlaying ? "Pause" : "Play"))
            .accessibilityIdentifier("story.play")
            .keyboardShortcut(.space, modifiers: [])

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.ds.divider).frame(height: 4)
                    Capsule().fill(Color.ds.accent).frame(width: geo.size.width * min(max(progress, 0), 1), height: 4)
                }
                .frame(maxHeight: .infinity)
                .contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0).onEnded { v in seek(v.location.x / max(geo.size.width, 1)) })
            }
            .frame(height: Tokens.Size.minTouch)
            .accessibilityElement()
            .accessibilityLabel(Text("Position"))
            .accessibilityValue(Text(timeText))
            .accessibilityAdjustableAction { dir in
                seek(min(max(progress + (dir == .increment ? 0.05 : -0.05), 0), 1))
            }

            Text(timeText).dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.secondary).monospacedDigit()

            Button(action: cycleRate) {
                Text(rateText).dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.ink)
                    .padding(.horizontal, Tokens.Space.m).frame(minHeight: 32)
                    .overlay(Capsule().strokeBorder(Color.ds.inputBorder, lineWidth: Tokens.Border.hairline))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text("Speed \(rateText)"))
            .accessibilityIdentifier("story.speed")

            primary
        }
        .padding(.vertical, Tokens.Space.m)
    }
}

/// The word panel (regular width) and gloss sheet (compact): headword Literata 36/600 accent, "pos · gloss" 15
/// `secondary`, the note 17, and **Hear it**.
struct WordPanel: View {
    let headword: String
    let posAndGloss: String
    var note: String?
    var canPlay: Bool
    let hearIt: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.m) {
            Text(ItalianText.attributed(headword, highlight: Color.ds.accent))
                .dsFont(Tokens.TypeScale.noteTitle)
                .foregroundStyle(Color.ds.accent)
            Text(posAndGloss).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
            if let note {
                MixedText(text: note, style: Tokens.TypeScale.uiBody)
            }
            if canPlay {
                Button("Hear it", action: hearIt)
                    .buttonStyle(.dsSecondarySmall)
                    .keyboardShortcut("l", modifiers: .command)
                    .accessibilityIdentifier("story.hearIt")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("story.wordPanel")
    }
}
