#if FEEDBACK
    import FeedbackKit
#endif
import LearningCore
import SwiftUI

/// Settings (`Settings.png`, docs/08 § Settings): every learner setting, grouped. Synced settings follow the
/// learner to their other devices; text size, speaking and reminders stay on this device.
struct SettingsScreen: View {
    let app: AppModel
    var sync: SyncSettingsModel?
    /// Study builds show Research → "Share anonymous learning data" (docs/12).
    var studyBuild = false
    /// Reminders, study data and the Debug menu (`AppServices`); previews leave it out.
    var services: AppServices?
    #if FEEDBACK
        /// In-app feedback, in Debug builds only (ADR-23); previews have none.
        @Environment(FeedbackCenter.self) private var feedback: FeedbackCenter?
        @State private var showsFeedbackSettings = false
    #endif

    var body: some View {
        let s = app.settings
        ScrollView {
            VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                Text("Settings").dsFont(Tokens.TypeScale.display).foregroundStyle(Color.ds.ink)
                    .accessibilityAddTraits(.isHeader)
                if let sync {
                    SyncSettingsSection(model: sync)
                } else {
                    SettingsGroup("Sync") {
                        Text(SyncStatusText.offInThisBuild).dsFont(Tokens.TypeScale.uiCallout)
                            .foregroundStyle(Color.ds.secondary)
                            .accessibilityIdentifier("settings.sync")
                    }
                }
                SettingsGroup("Practice") {
                    Stepper(value: binding(.goalDaysPerWeek, s.goalDaysPerWeek), in: 3...7) {
                        row("Weekly goal", value: "\(s.goalDaysPerWeek) days")
                    }
                    .accessibilityIdentifier("settings.goal")
                    Stepper(value: binding(.reviewDailyLimit, s.reviewDailyLimit), in: 20...200, step: 10) {
                        row("Reviews per day, at most", value: "\(s.reviewDailyLimit)")
                    }
                    .accessibilityIdentifier("settings.reviewLimit")
                    Toggle("English under stories", isOn: toggle(.displayEnglishUnderStories, s.englishUnderStories))
                        .accessibilityIdentifier("settings.english")
                    Toggle("Speaker names in stories", isOn: toggle(.displaySpeakerLabels, app.speakerLabelsNow))
                        .accessibilityIdentifier("settings.speakerLabels")
                    Picker("Audio speed", selection: number(.audioStoryRate, s.storyRate)) {
                        Text("0.8×").tag(0.8)
                        Text("1×").tag(1.0)
                    }
                    .accessibilityIdentifier("settings.audioSpeed")
                }
                SettingsGroup("You") {
                    TextField("Your name (for role-plays)", text: text(.profileName, s.profileName))
                        .accessibilityIdentifier("settings.name")
                    Picker("Forms that fit you", selection: text(.profileForms, s.profileForms.rawValue)) {
                        Text(mixed("Masculine", app.formsExample?.masculine)).tag("m")
                        Text(mixed("Feminine", app.formsExample?.feminine)).tag("f")
                        Text("Show me both").tag("both")
                    }
                    .accessibilityIdentifier("settings.forms")
                    // Used in role-plays (`{ME.home}`, `{ME.nationality}`): a learner who skipped it or moved sets it
                    // here.
                    Picker("Where you live", selection: text(.profileCountry, s.profileCountry ?? "")) {
                        // Offered only while unset: choosing it would store "", which docs/08 has no value for.
                        if (s.profileCountry ?? "").isEmpty { Text("Not set").tag("") }
                        ForEach(app.countryChoices) { c in
                            Text(mixed(c.nameEn, c.nameIt)).tag(c.id)
                        }
                    }
                    .accessibilityIdentifier("settings.country")
                    Picker("Why you're learning", selection: text(.profileReason, s.profileReason ?? "")) {
                        if (s.profileReason ?? "").isEmpty { Text("Not set").tag("") }
                        ForEach(OnboardingModel.reasons) { r in Text(r.title).tag(r.id) }
                    }
                    .accessibilityIdentifier("settings.reason")
                    Toggle("Only accept the forms that fit me", isOn: toggle(.answersStrictForms, s.strictForms))
                        .accessibilityIdentifier("settings.strictForms")
                }
                SettingsGroup("Moka") {
                    HStack(spacing: Tokens.Space.l) {
                        Mascot(pose: .hello, size: 56, decorative: true)
                        Toggle("Show Moka's hints and notes", isOn: toggle(.mascotHints, s.mascotHints))
                    }
                    .accessibilityIdentifier("settings.mascot")
                }
                if studyBuild {
                    SettingsGroup("Research") {
                        Toggle(
                            "Share anonymous learning data",
                            isOn: Binding(
                                get: { s.studyConsent?.granted ?? false }, set: { app.setStudyConsent($0) })
                        )
                        .accessibilityIdentifier("settings.research")
                        Text(
                            "Helps us check whether the app really teaches Italian. No name, no account, and you "
                                + "can stop any time."
                        )
                        .dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                        StudyDataRows(installID: s.studyInstallId, telemetry: services?.telemetry)
                    }
                }
                SettingsGroup("On this device") {
                    if let speech = services?.speech {
                        SpeechRows(model: speech, isOn: s.speechEnabled(available: true))
                    } else {
                        Toggle("Speaking exercises", isOn: toggle(.speechEnabled, s.speechEnabled(available: true)))
                            .accessibilityIdentifier("settings.speech")
                    }
                    VStack(alignment: .leading) {
                        row("Text size", value: "\(Int((s.textScale * 100).rounded()))%")
                        Slider(
                            value: number(.displayTextScale, s.textScale),
                            in: LearnerSettings.textScaleRange, step: 0.05)
                    }
                    .accessibilityIdentifier("settings.textSize")
                    if let reminders = services?.reminders {
                        ReminderRows(model: reminders)
                    } else {
                        Toggle("Daily reminder", isOn: toggle(.reminderEnabled, s.reminderEnabled))
                            .accessibilityIdentifier("settings.reminder")
                    }
                }
                SettingsGroup("About") {
                    AboutRows()
                }
                if let debug = services?.debug {
                    DebugSettingsSection(model: debug, storageError: app.lastStorageError)
                }
                #if FEEDBACK
                    if let feedback {
                        SettingsGroup("Feedback") {
                            Button("Feedback settings") { showsFeedbackSettings = true }
                                .buttonStyle(.dsTextLink)
                                .accessibilityIdentifier("settings.feedback.open")
                        }
                        .sheet(isPresented: $showsFeedbackSettings) {
                            FeedbackSettingsSheet(center: feedback)
                        }
                    }
                #endif
            }
            .toggleStyle(DSToggleStyle())
            .readableColumn()
            .padding(.vertical, Tokens.Space.xxl)
        }
        .background(Color.ds.surface)
    }

    /// "Masculine · americano" with the Italian part tagged it-IT, so VoiceOver reads it with the Italian voice
    /// (docs/07 § Accessibility); plain English when the pack gave no example.
    private func mixed(_ english: String, _ italian: String?) -> AttributedString {
        var label = AttributedString(english)
        if let italian, !italian.isEmpty {
            label.append(AttributedString(" · "))
            label.append(ItalianText.attributed(italian, highlight: Color.ds.ink))
        }
        return label
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

/// "Speaking exercises" with what the device can do (docs/09): a note when speech can't run here, and the
/// one-time download of the Italian model with its progress.
private struct SpeechRows: View {
    let model: SpeechSettingsModel
    let isOn: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.s) {
            Toggle(
                "Speaking exercises",
                isOn: Binding(get: { isOn }, set: { on in Task { await model.setEnabled(on) } })
            )
            .accessibilityIdentifier("settings.speech")
            if let note = model.note {
                Text(note).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                    .accessibilityIdentifier("settings.speech.note")
            }
            if let progress = model.downloadProgress {
                ProgressView(value: progress)
                    .accessibilityLabel("Downloading Italian speech recognition")
                    .accessibilityIdentifier("settings.speech.progress")
            } else if model.canDownload {
                Button("Download Italian speech recognition") { Task { await model.download() } }
                    .buttonStyle(.dsSecondarySmall)
                    .accessibilityIdentifier("settings.speech.download")
            }
        }
    }
}
