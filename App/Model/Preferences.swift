import Foundation
import Observation
import LanguageCore
import SRSKit

/// Preferences, synced through NSUbiquitousKeyValueStore (HANDOFF.md 5.1), with UserDefaults as
/// the local copy so they work signed out of iCloud. The device ID and onboarding state stay local.
///
/// Level and new items per day are kept per language (HANDOFF.md 5.3). Italian's stay under the keys
/// they had before German (`level`, `newItemsPerDay`), so older builds keep reading them; other
/// languages add a suffix (`level.de`).
@MainActor @Observable final class Preferences {
    private let cloud = NSUbiquitousKeyValueStore.default
    private let local = UserDefaults.standard

    /// The language the learner is studying now.
    var language: Language { didSet { save("activeLanguage", language.rawValue) } }
    private var levels: [Language: String]
    private var newItems: [Language: Int]

    /// The active language's level.
    var level: String {
        get { levels[language] ?? Self.defaultLevel(language) }
        set {
            levels[language] = newValue
            save(Self.key("level", language), newValue)
        }
    }

    /// The active language's new Remember items per day.
    var newItemsPerDay: Int {
        get { newItems[language] ?? 10 }
        set {
            newItems[language] = newValue
            save(Self.key("newItemsPerDay", language), newValue)
        }
    }

    var textScale: Double { didSet { save("textScale", textScale) } }
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
        language = (value("activeLanguage") as String?).flatMap(Language.init(rawValue:)) ?? .it
        var levels: [Language: String] = [:]
        var newItems: [Language: Int] = [:]
        for language in Language.allCases {
            levels[language] = value(Preferences.key("level", language))
            newItems[language] = value(Preferences.key("newItemsPerDay", language))
        }
        self.levels = levels
        self.newItems = newItems
        textScale = value("textScale") ?? 1.0
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

    /// Italian keeps the key as it is; other languages add their code: `level.de`.
    static func key(_ base: String, _ language: Language) -> String {
        language == .it ? base : "\(base).\(language.rawValue)"
    }

    static func defaultLevel(_ language: Language) -> String {
        language == .it ? "A2" : "A1"
    }

    private func save(_ key: String, _ value: Any) {
        cloud.set(value, forKey: key)
        local.set(value, forKey: key)
    }

    /// Picks up values another device changed.
    func reloadFromCloud() {
        if let v = cloud.string(forKey: "activeLanguage").flatMap(Language.init(rawValue:)), v != language {
            language = v
        }
        for language in Language.allCases {
            if let v = cloud.string(forKey: Self.key("level", language)), v != levels[language] {
                levels[language] = v
                local.set(v, forKey: Self.key("level", language))
            }
            if let v = cloud.object(forKey: Self.key("newItemsPerDay", language)) as? Int, v != newItems[language] {
                newItems[language] = v
                local.set(v, forKey: Self.key("newItemsPerDay", language))
            }
        }
        if let v = cloud.object(forKey: "textScale") as? Double, v != textScale { textScale = v }
        if let v = cloud.object(forKey: "translationInHelp") as? Bool, v != translationInHelp { translationInHelp = v }
        if let data = cloud.data(forKey: "fsrs"), let p = try? JSONDecoder().decode(FSRSParameters.self, from: data), p != fsrs {
            fsrs = p
        }
    }
}
