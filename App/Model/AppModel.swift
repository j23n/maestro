import Foundation
import NaturalLanguage
import Observation
import LanguageCore
import LexiconKit
import GrammarKit
import PackKit

/// One language's read-only content (HANDOFF.md 5.3): its bundled dictionary database and text
/// packs, from `Content/<lang>/`, plus the services on top of them.
struct LanguageContent {
    let language: Language
    let content: ContentDatabase?
    let lookup: Lookup?
    let conjugator: Conjugator?
    let library: PackLibrary
    let catalog: [CatalogText]
    let textLemmas: [String: [String: Int]]
    let grammarTopics: [GrammarTopicRow]
    let contentVersion: String

    init(language: Language, directory: URL?) {
        var db: ContentDatabase?
        if let directory {
            let path = directory.appendingPathComponent("content.sqlite").path
            if FileManager.default.fileExists(atPath: path) {
                db = try? ContentDatabase(path: path)
            }
        }
        self.language = language
        content = db
        lookup = db.map { Lookup(content: $0, lemmatizer: AppModel.taggerLemma(language)) }
        conjugator = db.map { Conjugator(content: $0) }
        library = PackLibrary(directories: directory.map { [$0.appendingPathComponent("packs")] } ?? [])
        catalog = db?.catalogTexts() ?? []
        textLemmas = db?.textLemmas() ?? [:]
        grammarTopics = db?.grammarTopics() ?? []
        contentVersion = db?.meta("content_version") ?? "none"
    }
}

/// The read-only content the app is built around, for the active language: the bundled dictionary
/// database and the text packs, plus the services on top of them. Learner data lives in SwiftData
/// (RememberStore).
@MainActor @Observable final class AppModel {
    let prefs: Preferences
    let speech = SpeechPlayer()
    /// Languages whose content is in the bundle, in Language order. The language choice only
    /// appears when there is more than one.
    let languages: [Language]
    /// The active language's content.
    private(set) var current: LanguageContent

    /// Set to jump to a tab from elsewhere (onboarding, a widget later).
    var selectedTab: AppTab = .read

    private let contentRoot: URL?
    @ObservationIgnored private var loaded: [Language: LanguageContent] = [:]
    private var textCache: [String: ReadingText] = [:]

    /// - Parameter contentRoot: the folder holding one folder per language (`it/content.sqlite`, `it/packs/`).
    init(contentRoot: URL? = AppModel.bundledContentRoot, prefs: Preferences = Preferences()) {
        self.prefs = prefs
        self.contentRoot = contentRoot
        let bundled = Language.allCases.filter { language in
            guard let root = contentRoot else { return false }
            let db = root.appendingPathComponent(language.rawValue).appendingPathComponent("content.sqlite")
            return FileManager.default.fileExists(atPath: db.path)
        }
        let available = bundled.isEmpty ? [Language.it] : bundled
        let start = available.contains(prefs.language) ? prefs.language : available[0]
        let content = LanguageContent(language: start, directory: contentRoot?.appendingPathComponent(start.rawValue))
        languages = available
        current = content
        loaded[start] = content
        TargetLanguage.current = start
        speech.language = start
        if prefs.language != start { prefs.language = start }
    }

    /// The bundle's content folder, `Content/`, with one folder per language (HANDOFF.md 5.3).
    static var bundledContentRoot: URL? {
        Bundle.main.url(forResource: "Content", withExtension: nil)
    }

    /// The language the learner is studying now.
    var language: Language { current.language }

    /// Switches every tab to another language. Its content loads on first use and stays loaded.
    func activate(_ language: Language) {
        guard languages.contains(language), language != current.language else { return }
        let next = loaded[language]
            ?? LanguageContent(language: language, directory: contentRoot?.appendingPathComponent(language.rawValue))
        loaded[language] = next
        TargetLanguage.current = language
        speech.language = language
        current = next
        prefs.language = language
    }

    var content: ContentDatabase? { current.content }
    var lookup: Lookup? { current.lookup }
    var conjugator: Conjugator? { current.conjugator }
    var library: PackLibrary { current.library }
    var catalog: [CatalogText] { current.catalog }
    var textLemmas: [String: [String: Int]] { current.textLemmas }
    var grammarTopics: [GrammarTopicRow] { current.grammarTopics }
    var contentVersion: String { current.contentVersion }

    var hasDictionary: Bool { content != nil }

    func text(_ id: String) -> ReadingText? {
        if let cached = textCache[id] { return cached }
        guard let text = try? library.load(id) else { return nil }
        textCache[id] = text
        return text
    }

    /// Every text in the library, with its level, for lists.
    var entries: [LibraryEntry] {
        library.entries.map { item in
            LibraryEntry(id: item.text.id, title: item.text.title, level: item.text.level ?? item.pack.manifest.level,
                         collection: item.pack.manifest.title, words: item.text.words, order: item.text.order,
                         isDraft: item.text.isDraft)
        }
    }

    /// IDs of the texts for this time of year, such as the winter texts in December.
    func featuredIDs(on date: Date = .now) -> Set<String> {
        Set(library.featured(on: date).map(\.text.id))
    }

    /// The grammar topics a text introduces, from its pack's manifest.
    func introduces(_ id: String) -> [String] {
        library.entries.first { $0.text.id == id }?.text.grammar?.introduces ?? []
    }

    func grammarTopic(_ id: String) -> GrammarTopicRow? {
        grammarTopics.first { $0.id == id } ?? content?.grammarTopic(id)
    }

    func grammarTitle(_ id: String) -> String {
        grammarTopic(id)?.title ?? id.replacingOccurrences(of: "-", with: " ").capitalized
    }

    /// NLTagger's lemma in the given language, the cascade's last resort before fuzzy matching
    /// (HANDOFF.md 3.2).
    nonisolated static func taggerLemma(_ language: Language) -> @Sendable (String) -> String? {
        let nlLanguage = NLLanguage(rawValue: language.rawValue)
        return { word in
            let tagger = NLTagger(tagSchemes: [.lemma])
            tagger.string = word
            tagger.setLanguage(nlLanguage, range: word.startIndex..<word.endIndex)
            let (tag, _) = tagger.tag(at: word.startIndex, unit: .word, scheme: .lemma)
            // German nouns keep their capital; Italian lemmas are lower case.
            return language == .de ? tag?.rawValue : tag?.rawValue.lowercased()
        }
    }
}

struct LibraryEntry: Identifiable, Hashable {
    let id: String
    let title: String
    let level: String
    let collection: String
    let words: Int
    let order: Int
    /// Not yet reviewed by a native speaker.
    var isDraft = false
}

enum AppTab: Hashable {
    case read, dictionary, verbs, remember, listen, settings
}

/// Places a NavigationStack can go.
enum Route: Hashable {
    case text(String)
    case questions(String)
    case practice(String)
    case entry(String)
    case verb(lemmaID: String, formTag: String?)
    case grammar(String)
    case grammarIndex
    case settings
}
