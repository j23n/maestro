import SwiftUI

/// First launch (HANDOFF.md 3.8): what's already on the device, and a level pick.
struct OnboardingView: View {
    let onDone: () -> Void
    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @State private var showVoiceGuide = false

    var body: some View {
        @Bindable var prefs = prefs
        NavigationStack {
            List {
                Section {
                    Text("Read graded Italian, tap any word for help, and keep what you want to remember.")
                        .font(.title3)
                        .padding(.vertical, 4)
                }
                Section("Ready offline") {
                    check(model.hasDictionary, "Dictionary built in", detail: model.hasDictionary ? nil : "Missing in this build")
                    check(!model.entries.isEmpty, "\(model.entries.count) starter texts included")
                    check(true, "Sentence translation", detail: "Apple's translation downloads Italian the first time you use it")
                    Button {
                        showVoiceGuide = true
                    } label: {
                        check(SpeechPlayer.hasEnhancedVoice, "Enhanced Italian voice",
                              detail: SpeechPlayer.hasEnhancedVoice ? nil : "Optional. Tap for how to install one")
                    }
                    .buttonStyle(.plain)
                    check(FileManager.default.ubiquityIdentityToken != nil, "iCloud sync",
                          detail: FileManager.default.ubiquityIdentityToken != nil ? nil : "Sign in to iCloud to sync across devices")
                }
                Section("Your level") {
                    Picker("Level", selection: $prefs.level) {
                        Text("A1 · Beginner").tag("A1")
                        Text("A2 · Elementary").tag("A2")
                        Text("B1 · Intermediate").tag("B1")
                        Text("B2 · Upper intermediate").tag("B2")
                    }
                    .pickerStyle(.inline)
                    .labelsHidden()
                }
            }
            .navigationTitle("Benvenuto")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Start") {
                        prefs.onboarded = true
                        onDone()
                    }
                }
            }
            .sheet(isPresented: $showVoiceGuide) { VoiceGuideView() }
        }
    }

    private func check(_ ok: Bool, _ title: String, detail: String? = nil) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: ok ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(ok ? Theme.added.foreground : Color.secondary)
                .accessibilityLabel(ok ? "Ready" : "Not set up")
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                if let detail { Text(detail).font(.footnote).foregroundStyle(.secondary) }
            }
        }
        .frame(minHeight: 36)
    }
}
