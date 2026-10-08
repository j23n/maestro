import LearningCore
import SwiftUI

/// Settings (`Settings.png`, docs/08 § Settings): every learner setting, grouped. Synced settings follow the
/// learner to their other devices; text size, speaking and reminders stay on this device.
struct SettingsScreen: View {
    let app: AppModel
    var sync: SyncSettingsModel?

    var body: some View {
        let s = app.settings
        ScrollView {
            VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                Text("Settings").dsFont(Tokens.TypeScale.display).foregroundStyle(Color.ds.ink)
                    .accessibilityAddTraits(.isHeader)
                if let sync {
                    SyncSettingsSection(model: sync)
                } else {
                    SettingsGroup(title: "Sync") {
                        Text(SyncStatusText.offInThisBuild).dsFont(Tokens.TypeScale.uiCallout)
                            .foregroundStyle(Color.ds.secondary)
                            .accessibilityIdentifier("settings.sync")
                    }
                }
                SettingsGroup(title: "Practice") {
                    Stepper(value: binding(.goalDaysPerWeek, s.goalDaysPerWeek), in: 3...7) {
                        row("Weekly goal", value: "\(s.goalDaysPerWeek) days")
                    }
                    .accessibilityIdentifier("settings.goal")
                    Divider()
                    Stepper(value: binding(.reviewDailyLimit, s.reviewDailyLimit), in: 20...200, step: 10) {
                        row("Reviews per day, at most", value: "\(s.reviewDailyLimit)")
                    }
                    .accessibilityIdentifier("settings.reviewLimit")
                    Divider()
                    Toggle("English under stories", isOn: toggle(.displayEnglishUnderStories, s.englishUnderStories))
                        .accessibilityIdentifier("settings.english")
                    Divider()
                    Picker("Audio speed", selection: number(.audioStoryRate, s.storyRate)) {
                        Text("0.8×").tag(0.8)
                        Text("1×").tag(1.0)
                    }
                    .accessibilityIdentifier("settings.audioSpeed")
                }
                SettingsGroup(title: "You") {
                    TextField("Your name (for role-plays)", text: text(.profileName, s.profileName))
                        .accessibilityIdentifier("settings.name")
                    Divider()
                    Picker("Forms that fit you", selection: text(.profileForms, s.profileForms.rawValue)) {
                        Text("nato, americano").tag("m")
                        Text("nata, americana").tag("f")
                        Text("Show me both").tag("both")
                    }
                    .accessibilityIdentifier("settings.forms")
                    Divider()
                    Toggle("Only accept the forms that fit me", isOn: toggle(.answersStrictForms, s.strictForms))
                        .accessibilityIdentifier("settings.strictForms")
                }
                SettingsGroup(title: "Moka") {
                    HStack(spacing: Tokens.Space.l) {
                        Mascot(pose: .hello, size: 56, decorative: true)
                        Toggle("Show Moka's hints and notes", isOn: toggle(.mascotHints, s.mascotHints))
                    }
                    .accessibilityIdentifier("settings.mascot")
                }
                SettingsGroup(title: "On this device") {
                    Toggle("Speaking exercises", isOn: toggle(.speechEnabled, s.speechEnabled(available: true)))
                        .accessibilityIdentifier("settings.speech")
                    Divider()
                    VStack(alignment: .leading) {
                        row("Text size", value: "\(Int((s.textScale * 100).rounded()))%")
                        Slider(
                            value: number(.displayTextScale, s.textScale),
                            in: LearnerSettings.textScaleRange, step: 0.05)
                    }
                    .accessibilityIdentifier("settings.textSize")
                    Divider()
                    Toggle("Daily reminder", isOn: toggle(.reminderEnabled, s.reminderEnabled))
                        .accessibilityIdentifier("settings.reminder")
                }
            }
            .toggleStyle(DSToggleStyle())
            .readableColumn()
            .padding(.vertical, Tokens.Space.xxl)
        }
        .background(Color.ds.surface)
    }

    private func row(_ title: String, value: String) -> some View {
        HStack {
            Text(title).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
            Spacer()
            Text(value).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
        }
    }

    private func toggle(_ key: SettingKey, _ current: Bool) -> Binding<Bool> {
        Binding(get: { current }, set: { app.set(key, to: .bool($0)) })
    }

    private func binding(_ key: SettingKey, _ current: Int) -> Binding<Int> {
        Binding(get: { current }, set: { app.set(key, to: .number(Double($0))) })
    }

    private func number(_ key: SettingKey, _ current: Double) -> Binding<Double> {
        Binding(get: { current }, set: { app.set(key, to: .number($0)) })
    }

    private func text(_ key: SettingKey, _ current: String) -> Binding<String> {
        Binding(get: { current }, set: { app.set(key, to: .string($0)) })
    }
}
