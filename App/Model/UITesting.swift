#if DEBUG
import Foundation
import ItalianCore
import PackKit

/// Launch arguments the screenshot UI test (`make screenshots`) uses to open a screen directly,
/// instead of tapping its way there. Debug builds only.
///
/// - `-uiTab dictionary`: the tab to show (read, dictionary, verbs, remember, listen).
/// - `-uiRoute entry:it:andare:v`: a screen to push on it (see `route(_:)`).
/// - `-uiQuery canti`: a search to type into the tab's search field.
/// - `-uiToken auto` or `-uiToken 3/5`: in the reader, the token (sentence/token) to open help for.
/// - `-uiSeed`: keep a few items from a starter text, so Remember has cards.
/// - `-uiReview`: open the Remember review.
enum UITestLaunch {
    private static var arguments: [String] { ProcessInfo.processInfo.arguments }

    static func value(_ name: String) -> String? {
        guard let i = arguments.firstIndex(of: "-" + name), arguments.indices.contains(i + 1) else { return nil }
        return arguments[i + 1]
    }

    static var tab: AppTab? {
        switch value("uiTab") {
        case "read": .read
        case "dictionary": .dictionary
        case "verbs": .verbs
        case "remember": .remember
        case "listen": .listen
        default: nil
        }
    }

    static var route: Route? { value("uiRoute").flatMap(route) }
    static var query: String? { value("uiQuery") }
    static var seed: Bool { arguments.contains("-uiSeed") }
    static var review: Bool { arguments.contains("-uiReview") }

    /// "text:<id>", "questions:<id>", "entry:<lemmaID>", "verb:<lemmaID>[@<formTag>]",
    /// "grammar:<id>", "grammarIndex" or "settings".
    static func route(_ string: String) -> Route? {
        let parts = string.split(separator: ":", maxSplits: 1).map(String.init)
        let arg = parts.count == 2 ? parts[1] : ""
        switch parts.first {
        case "text": return .text(arg)
        case "questions": return .questions(arg)
        case "entry": return .entry(arg)
        case "verb":
            let verb = arg.split(separator: "@", maxSplits: 1).map(String.init)
            return .verb(lemmaID: verb[0], formTag: verb.count == 2 ? verb[1] : nil)
        case "grammar": return .grammar(arg)
        case "grammarIndex": return .grammarIndex
        case "settings": return .settings
        default: return nil
        }
    }

    /// The token to open help for: the one given, or with "auto" the first verb form with a known
    /// lemma (else the first linked word).
    static func token(in text: ReadingText) -> (sentence: Int, token: Int)? {
        guard let value = value("uiToken") else { return nil }
        let sentences = text.sentences
        if value != "auto" {
            let n = value.split(separator: "/").compactMap { Int($0) }
            return n.count == 2 ? (n[0], n[1]) : nil
        }
        for (si, sentence) in sentences.enumerated() {
            if let k = sentence.tokens.firstIndex(where: { $0.form != nil && $0.lemmaID != nil }) { return (si, k) }
        }
        for (si, sentence) in sentences.enumerated() {
            if let k = sentence.tokens.firstIndex(where: { $0.lemmaID != nil }) { return (si, k) }
        }
        return nil
    }

    /// Keeps up to two items of each kind from the first starter text that has them.
    @MainActor static func seedRemember(_ store: RememberStore, model: AppModel) {
        var picked: [ItemKind: Int] = [:]
        var keys: Set<String> = []
        for entry in model.entries {
            guard let text = model.text(entry.id) else { continue }
            for sentence in text.sentences {
                for k in sentence.tokens.indices {
                    let help = HelpContent(text: text, sentence: sentence, tokenIndex: k, content: model.content)
                    for item in help.items where (picked[item.kind] ?? 0) < 2 && !keys.contains(item.key) {
                        guard !store.isKept(item.key) else { continue }
                        store.toggle(item)
                        picked[item.kind, default: 0] += 1
                        keys.insert(item.key)
                    }
                    if picked.values.reduce(0, +) >= 6 { return }
                }
            }
        }
    }
}
#endif
