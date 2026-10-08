import Foundation
import Observation

// Local reminders (docs/02, docs/08 `reminder.enabled`, `reminder.time`; task M3.10). Push from a server is a
// non-goal. Permission is asked only when the learner turns reminders on, never at launch.

enum NotificationAuthorization: Sendable, Equatable {
    case notDetermined, denied, authorized
}

protocol NotificationScheduling: Sendable {
    func authorization() async -> NotificationAuthorization
    func requestAuthorization() async -> Bool
    /// Replaces any existing reminder with one repeating daily at `hour:minute` local time.
    func scheduleDailyReminder(hour: Int, minute: Int, title: String, body: String) async throws
    func cancelReminders() async
}

/// `reminder.time` is stored as "HH:MM" (device setting).
struct ReminderTime: Sendable, Equatable {
    let hour: Int
    let minute: Int

    init(hour: Int, minute: Int) {
        self.hour = min(max(hour, 0), 23)
        self.minute = min(max(minute, 0), 59)
    }

    init?(_ text: String) {
        let parts = text.split(separator: ":")
        guard parts.count == 2, let h = Int(parts[0]), let m = Int(parts[1]), (0...23).contains(h),
            (0...59).contains(m)
        else { return nil }
        self.init(hour: h, minute: m)
    }

    var text: String { String(format: "%02d:%02d", hour, minute) }

    static let defaultTime = ReminderTime(hour: 19, minute: 0)
}

/// Turns the reminder settings into scheduled notifications.
@MainActor
@Observable
final class ReminderController {
    enum Outcome: Equatable {
        case scheduled, cancelled, permissionDenied
        /// `refresh` found that permission was never asked for (a restored database on a new install): nothing is
        /// scheduled, and only turning reminders on asks.
        case permissionNotAsked
    }

    private let scheduler: NotificationScheduling
    private(set) var lastOutcome: Outcome?

    static let title = "Time for a little Italian"
    static let body = "A short session keeps your words fresh. Moka is waiting."

    init(scheduler: NotificationScheduling) { self.scheduler = scheduler }

    /// Call when the learner flips the switch or changes the time. Returns the effective enabled state: false if
    /// the system refused permission (the Settings row then explains how to allow notifications).
    @discardableResult
    func apply(enabled: Bool, time: ReminderTime) async -> Bool {
        guard enabled else {
            await scheduler.cancelReminders()
            lastOutcome = .cancelled
            return false
        }
        var status = await scheduler.authorization()
        if status == .notDetermined {
            status = await scheduler.requestAuthorization() ? .authorized : .denied
        }
        guard status == .authorized else {
            lastOutcome = .permissionDenied
            return false
        }
        return await schedule(time) == .scheduled
    }

    /// At launch and when the time changes: puts the stored reminder back (or cancels it) without ever asking for
    /// permission (docs/08: permission is asked only when the learner turns reminders on).
    @discardableResult
    func refresh(enabled: Bool, time: ReminderTime) async -> Outcome {
        guard enabled else {
            await scheduler.cancelReminders()
            lastOutcome = .cancelled
            return .cancelled
        }
        switch await scheduler.authorization() {
        case .authorized:
            return await schedule(time)
        case .denied:
            lastOutcome = .permissionDenied
            return .permissionDenied
        case .notDetermined:
            lastOutcome = .permissionNotAsked
            return .permissionNotAsked
        }
    }

    private func schedule(_ time: ReminderTime) async -> Outcome {
        do {
            try await scheduler.scheduleDailyReminder(
                hour: time.hour, minute: time.minute, title: Self.title,
                body: Self.body)
            lastOutcome = .scheduled
        } catch {
            lastOutcome = .permissionDenied
        }
        return lastOutcome ?? .permissionDenied
    }
}

/// Records schedules for tests and previews.
final class FakeNotificationScheduler: NotificationScheduling, @unchecked Sendable {
    // @unchecked: state guarded by `lock`; tests read it after awaiting the calls.
    private let lock = NSLock()
    private var _status: NotificationAuthorization
    private let grants: Bool
    private var _scheduled: [ReminderTime] = []
    private var _requests = 0
    private var _cancels = 0

    init(status: NotificationAuthorization = .notDetermined, grants: Bool = true) {
        _status = status
        self.grants = grants
    }

    var scheduled: [ReminderTime] { lock.withLock { _scheduled } }
    var permissionRequests: Int { lock.withLock { _requests } }
    var cancels: Int { lock.withLock { _cancels } }

    /// The learner changes the permission in the system's settings.
    func setAuthorization(_ status: NotificationAuthorization) { lock.withLock { _status = status } }

    func authorization() async -> NotificationAuthorization { lock.withLock { _status } }

    func requestAuthorization() async -> Bool {
        lock.withLock {
            _requests += 1
            _status = grants ? .authorized : .denied
            return grants
        }
    }

    func scheduleDailyReminder(hour: Int, minute: Int, title: String, body: String) async throws {
        lock.withLock {
            _scheduled = [ReminderTime(hour: hour, minute: minute)]
        }
    }

    func cancelReminders() async {
        lock.withLock {
            _cancels += 1
            _scheduled = []
        }
    }
}
