#if FEEDBACK
    import FeedbackKit
#endif
import SwiftUI

extension EnvironmentValues {
    /// The learner's own words (`PersonalWords`), set at the root in builds with in-app feedback (ADR-23), where a
    /// feedback screenshot hides a text that holds one; empty in every other build.
    @Entry var personalWords: PersonalWords = .empty
}

extension View {
    /// Hides the view in a feedback screenshot (ADR-23): what the learner typed, said or chose. FeedbackKit paints
    /// over its frame, controls included (a picker's title, a text view). In builds without `FEEDBACK` it does
    /// nothing.
    func hiddenFromFeedback(_ hidden: Bool = true) -> some View {
        #if FEEDBACK
            feedbackHidden(hidden)
        #else
            self
        #endif
    }

    /// Hides the view in a feedback screenshot when `text` holds one of the learner's own words: a model answer or a
    /// hint the graders filled with their name or country. `ItalianText` and `MixedText` do it themselves.
    func hidesPersonalWords(in text: String) -> some View {
        modifier(PersonalWordsRedaction(text: text))
    }
}

private struct PersonalWordsRedaction: ViewModifier {
    let text: String
    @Environment(\.personalWords) private var words

    func body(content: Content) -> some View {
        content.hiddenFromFeedback(words.occur(in: text))
    }
}
