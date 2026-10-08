import Foundation
import LearningCore
import Observation

/// Settings → Daily reminder (task M3.10; docs/08 `reminder.enabled`, `reminder.time`, both device-scoped): the
/// switch, the time, and what the system allows. Permission is asked only when the learner turns the switch on;
/// launch and time changes reschedule without asking.
@MainActor
@Observable
final class ReminderSettingsModel {
    /// Why a reminder that is on can't be delivered.
    enum Problem: Equatable, Sendable {
        /// The learner refused notifications (now or in the system's settings).
        case notificationsOff
    }

    @ObservationIgnored private let app: AppModel
    @ObservationIgnored let controller: ReminderController
    private(set) var problem: Problem?

    init(app: AppModel, scheduler: any NotificationScheduling) {
        self.app = app
        controller = ReminderController(scheduler: scheduler)
    }

    var isOn: Bool { app.settings.reminderEnabled }
    /// The stored time, else 19:00.
    var time: ReminderTime { app.settings.reminderTime.flatMap(ReminderTime.init) ?? .defaultTime }

    /// The switch. Turning it on asks for permission when the system hasn't asked yet; refused, the switch stays
    /// off and Settings says how to allow notifications.
    func setEnabled(_ on: Bool) async {
        let scheduled = await controller.apply(enabled: on, time: time)
        app.set(.reminderEnabled, to: .bool(on && scheduled))
        problem = on && !scheduled ? .notificationsOff : nil
        await app.settle()
    }

    /// A new time: stored, and the reminder moves to it when reminders are on.
    func setTime(_ newTime: ReminderTime) async {
        guard newTime != time || app.settings.reminderTime == nil else { return }
        app.set(.reminderTime, to: .string(newTime.text))
        await app.settle()
        if isOn { await refresh() }
    }

    /// Launch: the daily reminder as the settings say, never asking for permission. Notifications switched off in
    /// the system's settings keep the switch on with a note (the reminder comes back once they're allowed again);
    /// a database restored onto an install that never asked turns the switch off.
    func refresh() async {
        switch await controller.refresh(enabled: isOn, time: time) {
        case .scheduled, .cancelled:
            problem = nil
        case .permissionDenied:
            problem = .notificationsOff
        case .permissionNotAsked:
            problem = nil
            app.set(.reminderEnabled, to: .bool(false))
            await app.settle()
        }
    }

    /// The note under the switch.
    var problemText: String? {
        switch problem {
        case .notificationsOff?:
            "Notifications are off for Italiano. Allow them in the system's Settings, under Notifications."
        case nil: nil
        }
    }
}

extension ReminderTime {
    /// The hour and minute of `date` in `calendar`'s time zone (the Settings time picker).
    init(date: Date, calendar: Calendar) {
        let parts = calendar.dateComponents([.hour, .minute], from: date)
        self.init(hour: parts.hour ?? Self.defaultTime.hour, minute: parts.minute ?? 0)
    }

    /// This time on `day` (the time picker's value).
    func date(on day: Date, calendar: Calendar) -> Date {
        calendar.date(bySettingHour: hour, minute: minute, second: 0, of: day) ?? day
    }
}
