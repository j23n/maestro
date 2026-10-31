import SwiftUI

/// First launch (HANDOFF.md 3.8): what's already on the device, and a level pick.
struct OnboardingView: View {
    let onDone: () -> Void
    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @State private var showVoiceGuide = false

    private static let levels: [(level: String, name: String)] = [
        ("A1", "Beginner"), ("A2", "Elementary"), ("B1", "Intermediate"), ("B2", "Upper int."),
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(italian: "Benvenuto!")
                        .font(.system(size: 36, weight: .regular, design: .serif))
                    Text("Read graded Italian, tap any word for help, and keep what you want to remember. Everything works offline.")
                        .font(.body)
                        .foregroundStyle(.secondary)
                }
                .padding(.top, 24)

                VStack(spacing: 0) {
                    check(model.hasDictionary, "Dictionary and verb tables",
                          detail: model.hasDictionary ? "Built in" : "Missing in this build")
                    Divider()
                    check(!model.entries.isEmpty, "Reading library", detail: "\(model.entries.count) starter texts included")
                    Divider()
                    check(true, "Sentence translation", detail: "Apple's translation downloads Italian the first time you use it")
                    Divider()
                    check(SpeechPlayer.hasEnhancedVoice, "Natural Italian voice",
                          detail: SpeechPlayer.hasEnhancedVoice ? "Installed" : "Optional, installed from Settings") {
                        if !SpeechPlayer.hasEnhancedVoice {
                            Button("Show me") { showVoiceGuide = true }
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(Theme.ink)
                                .padding(.horizontal, 14)
                                .frame(minHeight: 36)
                                .overlay(Capsule().stroke(Theme.borderControl))
                                .frame(minHeight: 44)
                                .buttonStyle(.plain)
                        }
                    }
                    Divider()
                    let icloud = FileManager.default.ubiquityIdentityToken != nil
                    check(icloud, "iCloud sync", detail: icloud ? "Progress follows you to your other devices" : "Sign in to iCloud to sync across devices")
                }
                .background(RoundedRectangle(cornerRadius: 14).fill(Theme.background))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.hairline))

                VStack(alignment: .leading, spacing: 4) {
                    Text("Where should we start?").font(.headline)
                    Text("Sets which texts are suggested first. Change it any time.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                HStack(spacing: 8) {
                    ForEach(Self.levels, id: \.level) { item in
                        levelTile(item.level, item.name)
                    }
                }

                Button("Start reading") {
                    prefs.onboarded = true
                    onDone()
                }
                .buttonStyle(PrimaryButtonStyle())
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
            .frame(maxWidth: 560)
            .frame(maxWidth: .infinity)
        }
        .background(Theme.background)
        .sheet(isPresented: $showVoiceGuide) { VoiceGuideView() }
    }

    private func levelTile(_ level: String, _ name: String) -> some View {
        let selected = prefs.level == level
        return Button {
            prefs.level = level
        } label: {
            VStack(spacing: 2) {
                Text(level).font(.headline)
                Text(name).font(.caption2).lineLimit(1).minimumScaleFactor(0.8)
            }
            .frame(maxWidth: .infinity, minHeight: 60)
            .foregroundStyle(selected ? Theme.background : Theme.ink)
            .background(RoundedRectangle(cornerRadius: 10).fill(selected ? Theme.ink : Color.clear))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(selected ? Color.clear : Theme.borderInput))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(level), \(name)")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func check<Trailing: View>(_ ok: Bool, _ title: String, detail: String? = nil,
                                       @ViewBuilder trailing: () -> Trailing = { EmptyView() }) -> some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: ok ? "checkmark.circle.fill" : "circle")
                .font(.title3)
                .foregroundStyle(ok ? Theme.added.foreground : Color.secondary)
                .accessibilityLabel(ok ? "Ready" : "Not set up")
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.body.weight(.semibold))
                if let detail { Text(detail).font(.footnote).foregroundStyle(.secondary) }
            }
            Spacer(minLength: 8)
            trailing()
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .frame(minHeight: 52)
    }
}
