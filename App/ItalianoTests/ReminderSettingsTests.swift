import Foundation
import LearningCore
import Testing

@testable import Italiano

/// M3.10: `reminder.enabled` and `reminder.time` drive the daily reminder; permission is asked only when the learner
/// turns reminders on (docs/08).
@MainActor
@Suite struct ReminderSettingsTests {
    let shell = ShellTestApp()

    @Test func turningOnAsksOnceSchedulesAndTurningOffCancels() async throws {
        let app = await shell.started()
        let fake = FakeNotificationScheduler()
        let reminders = ReminderSettingsModel(app: app, scheduler: fake)
        await reminders.refresh()  // launch with reminders off: nothing asked
        #expect(fake.permissionRequests == 0 && fake.scheduled.isEmpty)
        #expect(!reminders.isOn && reminders.time == .defaultTime)

        await reminders.setEnabled(true)
        #expect(fake.permissionRequests == 1)
        #expect(fake.scheduled == [ReminderTime(hour: 19, minute: 0)])
        #expect(reminders.isOn && app.settings.reminderEnabled && reminders.problem == nil)

        await reminders.setTime(ReminderTime(hour: 8, minute: 15))
        #expect(app.settings.reminderTime == "08:15")
        #expect(fake.scheduled == [ReminderTime(hour: 8, minute: 15)])
        #expect(fake.permissionRequests == 1)

        await reminders.setEnabled(false)
        #expect(fake.scheduled.isEmpty && !app.settings.reminderEnabled)

        // A new time while off is stored but schedules nothing.
        await reminders.setTime(ReminderTime(hour: 7, minute: 0))
        #expect(fake.scheduled.isEmpty && reminders.time == ReminderTime(hour: 7, minute: 0))
        #expect(fake.permissionRequests == 1)
    }

    @Test func refusedPermissionKeepsTheSwitchOffWithANote() async throws {
        let app = await shell.started()
        let reminders = ReminderSettingsModel(app: app, scheduler: FakeNotificationScheduler(grants: false))
        await reminders.setEnabled(true)
        #expect(!app.settings.reminderEnabled)
        #expect(reminders.problem == .notificationsOff && reminders.problemText != nil)
        await reminders.setEnabled(false)
        #expect(reminders.problem == nil)
    }

    @Test func launchReschedulesWithoutAsking() async throws {
        let app = await shell.started()
        let fake = FakeNotificationScheduler()
        let first = ReminderSettingsModel(app: app, scheduler: fake)
        await first.setEnabled(true)
        await first.setTime(ReminderTime(hour: 21, minute: 30))

        // Next launch: the stored reminder is put back; nobody is asked.
        let relaunched = FakeNotificationScheduler(status: .authorized)
        let again = ReminderSettingsModel(app: app, scheduler: relaunched)
        await again.refresh()
        #expect(relaunched.scheduled == [ReminderTime(hour: 21, minute: 30)])
        #expect(relaunched.permissionRequests == 0)

        // Notifications switched off in the system's settings: the switch stays on, with a note, and nothing asks.
        let denied = FakeNotificationScheduler(status: .denied)
        let blocked = ReminderSettingsModel(app: app, scheduler: denied)
        await blocked.refresh()
        #expect(denied.permissionRequests == 0 && denied.scheduled.isEmpty)
        #expect(app.settings.reminderEnabled && blocked.problem == .notificationsOff)
        // …and allowed again: the next refresh schedules it.
        denied.setAuthorization(.authorized)
        await blocked.refresh()
        #expect(denied.scheduled == [ReminderTime(hour: 21, minute: 30)] && blocked.problem == nil)

        // A database restored onto an install that never asked: the switch goes off; still nothing asks.
        let fresh = FakeNotificationScheduler(status: .notDetermined)
        let restored = ReminderSettingsModel(app: app, scheduler: fresh)
        await restored.refresh()
        #expect(fresh.permissionRequests == 0 && fresh.scheduled.isEmpty)
        #expect(!app.settings.reminderEnabled)
    }

    @Test func launchServicesRefreshReminders() async throws {
        let app = await shell.started()
        let fake = FakeNotificationScheduler(status: .authorized)
        let services = AppServices(
            config: .preview, app: app, notifications: fake, telemetry: nil, debug: nil)
        _ = try await app.store?.set(.reminderEnabled, to: .bool(true))
        _ = try await app.store?.set(.reminderTime, to: .string("06:45"))
        for _ in 0..<200 where !app.settings.reminderEnabled { try await Task.sleep(for: .milliseconds(5)) }
        await services.afterLaunch(arguments: [])
        #expect(fake.scheduled == [ReminderTime(hour: 6, minute: 45)] && fake.permissionRequests == 0)
    }

    @Test func timePickerDates() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try #require(TimeZone(identifier: "Europe/Rome"))
        let day = Date(timeIntervalSince1970: 1_791_271_800)  // 6 Oct 2026, 09:30 in Rome
        let date = ReminderTime(hour: 7, minute: 5).date(on: day, calendar: calendar)
        #expect(calendar.component(.hour, from: date) == 7 && calendar.component(.minute, from: date) == 5)
        #expect(ReminderTime(date: date, calendar: calendar) == ReminderTime(hour: 7, minute: 5))
        #expect(ReminderTime(date: day, calendar: calendar) == ReminderTime(hour: 9, minute: 30))
    }
}
