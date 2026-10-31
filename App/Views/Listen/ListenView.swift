import SwiftData
import SwiftUI
import PackKit

/// The Listen tab (HANDOFF.md 3.6): voice-quality banner, Continue, Listen first, Listen again.
struct ListenView: View {
    @Environment(AppModel.self) private var model
    @Query(sort: \TextProgress.updatedAt, order: .reverse) private var progress: [TextProgress]
    @State private var showVoiceGuide = false

    var body: some View {
        let read = Set(progress.filter { $0.maxFractionRead > 0.5 || $0.finishedAt != nil }.map(\.textID))
        let entries = model.entries
        List {
            if !SpeechPlayer.hasEnhancedVoice {
                Section {
                    Button {
                        showVoiceGuide = true
                    } label: {
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: "waveform.badge.exclamationmark").foregroundStyle(Theme.warning.foreground)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Only the standard Italian voice is installed").font(.subheadline.weight(.semibold))
                                Text("An Enhanced or Premium voice sounds much more natural. Tap for how to get one.")
                                    .font(.footnote)
                            }
                        }
                        .foregroundStyle(Theme.warning.foreground)
                    }
                    .buttonStyle(.plain)
                    .listRowBackground(Theme.warning.background)
                }
            }
            if let current = model.speech.currentSegment, let textID = current.id.split(separator: "#").first.map(String.init),
               let entry = entries.first(where: { $0.id == textID }) {
                Section("Continue") {
                    NavigationLink {
                        PlayerView(textID: entry.id)
                    } label: {
                        ListenRow(entry: entry, systemImage: model.speech.isPlaying ? "speaker.wave.2.fill" : "play.fill")
                    }
                }
            }
            let fresh = entries.filter { !read.contains($0.id) }
            if !fresh.isEmpty {
                Section {
                    ForEach(fresh) { entry in
                        NavigationLink { PlayerView(textID: entry.id, listenFirst: true) } label: {
                            ListenRow(entry: entry, systemImage: "ear")
                        }
                    }
                } header: {
                    Text("Listen first")
                } footer: {
                    Text("Hear a new text before you read it, with the text hidden.")
                }
            }
            let again = entries.filter { read.contains($0.id) }
            if !again.isEmpty {
                Section("Listen again") {
                    ForEach(again) { entry in
                        NavigationLink { PlayerView(textID: entry.id) } label: {
                            ListenRow(entry: entry, systemImage: "arrow.counterclockwise")
                        }
                    }
                }
            }
        }
        .navigationTitle("Listen")
        .sheet(isPresented: $showVoiceGuide) { VoiceGuideView() }
    }
}

struct ListenRow: View {
    let entry: LibraryEntry
    let systemImage: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: systemImage)
                .frame(width: 32, height: 32)
                .foregroundStyle(Color.accentColor)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(italian: entry.title).font(.system(.body, design: .serif).weight(.semibold))
                HStack(spacing: 6) {
                    LevelTag(level: entry.level)
                    Text("about \(max(1, entry.words / 130)) min").font(.footnote).foregroundStyle(.secondary)
                }
            }
        }
    }
}

struct VoiceGuideView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    #if os(macOS)
                    Text("Open System Settings › Accessibility › Spoken Content › System Voice › Manage Voices.")
                    #else
                    Text("Open Settings › Accessibility › Read & Speak › Voices.")
                    #endif
                    Text("Choose Italian, then download a voice marked Enhanced or Premium, such as Alice or Federica.")
                    Text("Come back to Maestro: it uses the best Italian voice it finds.")
                } footer: {
                    Text("Apps can't download voices themselves, so this takes a trip to Settings.")
                }
            }
            .navigationTitle("Better Italian voices")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
        }
    }
}
