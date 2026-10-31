import SwiftUI
import UserNotifications

/// Settings (HANDOFF.md 3.8).
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @State private var iCloudStatus = "Checking…"

    var body: some View {
        @Bindable var prefs = prefs
        Form {
            Section("Sync") {
                LabeledContent("iCloud", value: iCloudStatus)
            }
            Section("Offline") {
                LabeledContent("Dictionary", value: model.hasDictionary ? "Built in (\(model.contentVersion))" : "Missing")
                LabeledContent("Texts on this device", value: "\(model.entries.count)")
                LabeledContent("Italian voice", value: SpeechPlayer.hasEnhancedVoice ? "Enhanced" : "Standard only")
            }
            Section("Reading") {
                Picker("Level", selection: $prefs.level) {
                    ForEach(["A1", "A2", "B1", "B2"], id: \.self) { Text($0).tag($0) }
                }
                Picker("Text size", selection: $prefs.textScale) {
                    Text("Small").tag(0.85)
                    Text("Default").tag(1.0)
                    Text("Large").tag(1.15)
                    Text("Larger").tag(1.3)
                    Text("Largest").tag(1.5)
                }
                Toggle("Sentence translation in help", isOn: $prefs.translationInHelp)
            }
            Section {
                Stepper("New items per day: \(prefs.newItemsPerDay)", value: $prefs.newItemsPerDay, in: 0...50)
                Toggle("Daily reminder", isOn: $prefs.reminderEnabled)
                if prefs.reminderEnabled {
                    DatePicker("Time", selection: reminderTime, displayedComponents: .hourAndMinute)
                }
            } header: {
                Text("Remember")
            }
            Section("Acknowledgements") {
                Text("Dictionary entries and inflections from Wiktionary (via kaikki.org), CC BY-SA 4.0.")
                Text("Inflected forms from Morph-it!, CC BY-SA 2.0.")
                Text("Example sentences from Tatoeba, CC BY 2.0 FR.")
            }
            .font(.footnote)
            Section {
                LabeledContent("Version", value: version)
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Settings")
        .task { await checkICloud() }
        .onChange(of: prefs.reminderEnabled) { _, on in Task { await Reminder.update(enabled: on, minutes: prefs.reminderMinutes) } }
        .onChange(of: prefs.reminderMinutes) { _, m in Task { await Reminder.update(enabled: prefs.reminderEnabled, minutes: m) } }
    }

    private var reminderTime: Binding<Date> {
        Binding {
            Calendar.current.startOfDay(for: .now).addingTimeInterval(Double(prefs.reminderMinutes * 60))
        } set: { date in
            let c = Calendar.current.dateComponents([.hour, .minute], from: date)
            prefs.reminderMinutes = (c.hour ?? 19) * 60 + (c.minute ?? 0)
        }
    }

    private var version: String {
        let v = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?"
        let b = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "?"
        return "\(v) (\(b))"
    }

    private func checkICloud() async {
        guard FileManager.default.ubiquityIdentityToken != nil else {
            iCloudStatus = "Signed out: progress stays on this device"
            return
        }
        iCloudStatus = "On"
    }
}

/// The daily Remember reminder: one repeating local notification.
enum Reminder {
    static let id = "remember-daily"

    @MainActor static func update(enabled: Bool, minutes: Int) async {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: [id])
        guard enabled else { return }
        let granted = (try? await center.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        guard granted else { return }
        let content = UNMutableNotificationContent()
        content.title = "Time for Remember"
        content.body = "A few cards are waiting, with the sentences they came from."
        var when = DateComponents()
        when.hour = minutes / 60
        when.minute = minutes % 60
        let request = UNNotificationRequest(identifier: id, content: content,
                                            trigger: UNCalendarNotificationTrigger(dateMatching: when, repeats: true))
        try? await center.add(request)
    }
}
