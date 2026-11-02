import Foundation
import LanguageCore
import Synchronization

/// The language the learner is studying now (HANDOFF.md 5.3), for code that has no model at hand:
/// attributed strings marked for VoiceOver, speech voices, UI copy that names the language.
/// AppModel sets it whenever the active language changes.
enum TargetLanguage {
    private static let storage = Mutex<Language>(.it)

    static var current: Language {
        get { storage.withLock { $0 } }
        set { storage.withLock { $0 = newValue } }
    }
}
