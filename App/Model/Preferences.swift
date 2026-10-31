import Foundation
import Observation
import SRSKit

/// Preferences, synced through NSUbiquitousKeyValueStore (HANDOFF.md 5.1), with UserDefaults as
/// the local copy so they work signed out of iCloud. The device ID and onboarding state stay local.
@MainActor @Observable final class Preferences {
    private let cloud = NSUbiquitousKeyValueStore.default
    private let local = UserDefaults.standard

    var level: String { didSet { save("level", level) } }
    var textScale: Double { didSet { save("textScale", textScale) } }
    var newItemsPerDay: Int { didSet { save("newItemsPerDay", newItemsPerDay) } }
    var translationInHelp: Bool { didSet { save("translationInHelp", translationInHelp) } }
    var reminderEnabled: Bool { didSet { save("reminderEnabled", reminderEnabled) } }
    var reminderMinutes: Int { didSet { save("reminderMinutes", reminderMinutes) } }
    var speechRate: Double { didSet { save("speechRate", speechRate) } }
    var fsrs: FSRSParameters {
        didSet {
            if let data = try? JSONEncoder().encode(fsrs) { save("fsrs", data) }
        }
    }

    var onboarded: Bool { didSet { local.set(onboarded, forKey: "onboarded") } }
    let deviceID: String

    init() {
        func value<T>(_ key: String) -> T? {
            (NSUbiquitousKeyValueStore.default.object(forKey: key) as? T) ?? (UserDefaults.standard.object(forKey: key) as? T)
        }
        level = value("level") ?? "A2"
        textScale = value("textScale") ?? 1.0
        newItemsPerDay = value("newItemsPerDay") ?? 10
        translationInHelp = value("translationInHelp") ?? true
        reminderEnabled = value("reminderEnabled") ?? false
        reminderMinutes = value("reminderMinutes") ?? 19 * 60
        speechRate = value("speechRate") ?? 0.9
        if let data: Data = value("fsrs"), let params = try? JSONDecoder().decode(FSRSParameters.self, from: data) {
            fsrs = params
        } else {
            fsrs = .default
        }
        onboarded = UserDefaults.standard.bool(forKey: "onboarded")
        if let id = UserDefaults.standard.string(forKey: "deviceID") {
            deviceID = id
        } else {
            let id = UUID().uuidString
            UserDefaults.standard.set(id, forKey: "deviceID")
            deviceID = id
        }
        cloud.synchronize()
    }

    private func save(_ key: String, _ value: Any) {
        cloud.set(value, forKey: key)
        local.set(value, forKey: key)
    }

    /// Picks up values another device changed.
    func reloadFromCloud() {
        if let v = cloud.string(forKey: "level"), v != level { level = v }
        if let v = cloud.object(forKey: "textScale") as? Double, v != textScale { textScale = v }
        if let v = cloud.object(forKey: "newItemsPerDay") as? Int, v != newItemsPerDay { newItemsPerDay = v }
        if let v = cloud.object(forKey: "translationInHelp") as? Bool, v != translationInHelp { translationInHelp = v }
        if let data = cloud.data(forKey: "fsrs"), let p = try? JSONDecoder().decode(FSRSParameters.self, from: data), p != fsrs {
            fsrs = p
        }
    }
}
