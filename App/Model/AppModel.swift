import Foundation
import NaturalLanguage
import Observation
import ItalianCore
import LexiconKit
import GrammarKit
import PackKit

/// The read-only content the app is built around: the bundled dictionary database and the text
/// packs, plus the services on top of them. Learner data lives in SwiftData (RememberStore).
@MainActor @Observable final class AppModel {
    let content: ContentDatabase?
    let lookup: Lookup?
    let conjugator: Conjugator?
    let library: PackLibrary
    let catalog: [CatalogText]
    let textLemmas: [String: [String: Int]]
    let grammarTopics: [GrammarTopicRow]
    let contentVersion: String
    let prefs = Preferences()
    let speech = SpeechPlayer()

    /// Set to jump to a tab from elsewhere (onboarding, a widget later).
    var selectedTab: AppTab = .read

    private var textCache: [String: ReadingText] = [:]

    init(contentDirectory: URL? = AppModel.bundledContentDirectory) {
        var db: ContentDatabase?
        if let dir = contentDirectory {
            let path = dir.appendingPathComponent("content.sqlite").path
            if FileManager.default.fileExists(atPath: path) {
                db = try? ContentDatabase(path: path)
            }
        }
        content = db
        lookup = db.map { Lookup(content: $0, lemmatizer: AppModel.taggerLemma) }
        conjugator = db.map { Conjugator(content: $0) }
        let packDirs = contentDirectory.map { [$0.appendingPathComponent("packs")] } ?? []
        library = PackLibrary(directories: packDirs)
        catalog = db?.catalogTexts() ?? []
        textLemmas = db?.textLemmas() ?? [:]
        grammarTopics = db?.grammarTopics() ?? []
        contentVersion = db?.meta("content_version") ?? "none"
    }

    static var bundledContentDirectory: URL? {
        Bundle.main.url(forResource: "Content", withExtension: nil)
    }

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
        Set(library.featured(on: date, calendar: .current).map(\.text.id))
    }

    func grammarTopic(_ id: String) -> GrammarTopicRow? {
        grammarTopics.first { $0.id == id } ?? content?.grammarTopic(id)
    }

    func grammarTitle(_ id: String) -> String {
        grammarTopic(id)?.title ?? id.replacingOccurrences(of: "-", with: " ").capitalized
    }

    /// NLTagger's lemma, the cascade's last resort before fuzzy matching (HANDOFF.md 3.2).
    nonisolated static let taggerLemma: @Sendable (String) -> String? = { word in
        let tagger = NLTagger(tagSchemes: [.lemma])
        tagger.string = word
        tagger.setLanguage(.italian, range: word.startIndex..<word.endIndex)
        let (tag, _) = tagger.tag(at: word.startIndex, unit: .word, scheme: .lemma)
        return tag?.rawValue.lowercased()
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
    case entry(String)
    case verb(lemmaID: String, formTag: String?)
    case grammar(String)
    case grammarIndex
    case settings
}
