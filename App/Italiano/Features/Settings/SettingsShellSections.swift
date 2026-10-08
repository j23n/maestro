import SwiftUI

/// Settings → On this device → Daily reminder and its time (task M3.10, docs/08). Turning the switch on is the only
/// place the app asks for notification permission.
struct ReminderRows: View {
    let model: ReminderSettingsModel

    var body: some View {
        Toggle(
            "Daily reminder",
            isOn: Binding(get: { model.isOn }, set: { on in Task { await model.setEnabled(on) } })
        )
        .accessibilityIdentifier("settings.reminder")
        if model.isOn {
            DatePicker(
                "Reminder time",
                selection: Binding(
                    get: { model.time.date(on: Date(), calendar: .current) },
                    set: { date in Task { await model.setTime(ReminderTime(date: date, calendar: .current)) } }),
                displayedComponents: .hourAndMinute
            )
            .dsFont(Tokens.TypeScale.uiBody)
            .accessibilityIdentifier("settings.reminderTime")
        }
        if let note = model.problemText {
            Text(note).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("settings.reminderNote")
        }
    }
}

/// Settings → Research, study builds (docs/12): the install ID a participant can quote, and "Delete my study data".
struct StudyDataRows: View {
    let installID: String?
    /// Nil when this build can't reach the study server (no endpoint or token): nothing to delete from here.
    let telemetry: StudyTelemetry?
    @State private var confirmDelete = false

    var body: some View {
        if let installID {
            VStack(alignment: .leading, spacing: Tokens.Space.xs) {
                Text("Your study ID").dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                Text(installID).font(.footnote.monospaced()).foregroundStyle(Color.ds.secondary)
                    .textSelection(.enabled)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("settings.installId")
        }
        if let telemetry, telemetry.canDelete {
            Button("Delete my study data", role: .destructive) { confirmDelete = true }
                .buttonStyle(.dsTextLink)
                .disabled(telemetry.deleteState == .deleting)
                .accessibilityIdentifier("settings.deleteStudyData")
                .confirmationDialog("Delete your study data?", isPresented: $confirmDelete, titleVisibility: .visible) {
                    Button("Delete", role: .destructive) { Task { await telemetry.deleteStudyData() } }
                        .accessibilityIdentifier("settings.deleteStudyDataConfirm")
                    Button("Cancel", role: .cancel) {}
                } message: {
                    Text(
                        "This turns sharing off and asks the research team's server to delete everything sent with "
                            + "your study ID. Your progress stays on your devices.")
                }
            if let status = telemetry.deleteStatusText {
                Text(status).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                    .accessibilityIdentifier("settings.deleteStudyDataStatus")
            }
        }
    }
}

/// Settings → About → Acknowledgements.
struct AboutRows: View {
    @State private var showAcknowledgements = false

    var body: some View {
        Button("Acknowledgements") { showAcknowledgements = true }
            .buttonStyle(.dsTextLink)
            .accessibilityIdentifier("settings.acknowledgements")
            .sheet(isPresented: $showAcknowledgements) {
                // Ideal, not minimum, sizes: a Mac sheet takes them; an iPhone sheet keeps the screen's width.
                AcknowledgementsView { showAcknowledgements = false }
                    .frame(idealWidth: 560, idealHeight: 640)
            }
    }
}
