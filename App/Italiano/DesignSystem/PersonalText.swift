import SwiftUI

extension EnvironmentValues {
    /// The learner's own words (`PersonalWords`), set at the root in builds with in-app feedback (ADR-23), where a
    /// feedback screenshot hides a text that holds one; empty in every other build, where nothing changes.
    @Entry var personalWords: PersonalWords = .empty
}

extension View {
    /// Marks the view privacy-sensitive when `text` holds one of the learner's own words, so a feedback screenshot
    /// redacts it (ADR-23). `ItalianText` and `MixedText` do it themselves; use it where the learner's own input or a
    /// model answer is shown another way.
    func hidesPersonalWords(in text: String) -> some View {
        modifier(PersonalWordsRedaction(text: text))
    }
}

private struct PersonalWordsRedaction: ViewModifier {
    let text: String
    @Environment(\.personalWords) private var words

    func body(content: Content) -> some View {
        content.privacySensitive(words.occur(in: text))
    }
}
