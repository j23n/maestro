import LearningCore
import SwiftUI

// The Mac menu bar (docs/07 § Navigation, task M3.8): the Lesson menu and the View menu's text-size and English
// items. The player's views publish what each Lesson item does through focused scene values, next to the button
// that does the same thing (and already has the same shortcut for iPad keyboards); an item is disabled while
// nothing publishes it.

/// One Lesson-menu action published by the view on screen.
struct LessonMenuAction {
    let perform: () -> Void
}

/// The Lesson menu's items, in menu order.
enum LessonMenuItem: CaseIterable {
    case check, showHint, listenAgain, showAnswer, closeLesson

    var keyPath: WritableKeyPath<FocusedValues, LessonMenuAction?> {
        switch self {
        case .check: \.lessonCheck
        case .showHint: \.lessonShowHint
        case .listenAgain: \.lessonListenAgain
        case .showAnswer: \.lessonShowAnswer
        case .closeLesson: \.lessonClose
        }
    }
}

private struct LessonCheckKey: FocusedValueKey { typealias Value = LessonMenuAction }
private struct LessonShowHintKey: FocusedValueKey { typealias Value = LessonMenuAction }
private struct LessonListenAgainKey: FocusedValueKey { typealias Value = LessonMenuAction }
private struct LessonShowAnswerKey: FocusedValueKey { typealias Value = LessonMenuAction }
private struct LessonCloseKey: FocusedValueKey { typealias Value = LessonMenuAction }
private struct ShowEnglishKey: FocusedValueKey { typealias Value = Binding<Bool> }

extension FocusedValues {
    var lessonCheck: LessonMenuAction? {
        get { self[LessonCheckKey.self] }
        set { self[LessonCheckKey.self] = newValue }
    }
    var lessonShowHint: LessonMenuAction? {
        get { self[LessonShowHintKey.self] }
        set { self[LessonShowHintKey.self] = newValue }
    }
    var lessonListenAgain: LessonMenuAction? {
        get { self[LessonListenAgainKey.self] }
        set { self[LessonListenAgainKey.self] = newValue }
    }
    var lessonShowAnswer: LessonMenuAction? {
        get { self[LessonShowAnswerKey.self] }
        set { self[LessonShowAnswerKey.self] = newValue }
    }
    var lessonClose: LessonMenuAction? {
        get { self[LessonCloseKey.self] }
        set { self[LessonCloseKey.self] = newValue }
    }
    /// View → Show English: the story's or the conversation's "English under each line".
    var showEnglish: Binding<Bool>? {
        get { self[ShowEnglishKey.self] }
        set { self[ShowEnglishKey.self] = newValue }
    }
}

extension View {
    /// Publishes this view's action for a Lesson-menu item while it is on screen (and enabled).
    func lessonMenu(_ item: LessonMenuItem, isEnabled: Bool = true, perform action: @escaping () -> Void) -> some View {
        focusedSceneValue(item.keyPath, isEnabled ? LessonMenuAction(perform: action) : nil)
    }

    /// Lets View → Show English (⇧⌘E) toggle this screen's English lines.
    func showEnglishMenu(_ isOn: Binding<Bool>) -> some View {
        focusedSceneValue(\.showEnglish, isOn)
    }

    /// The learner's `display.textScale` for everything below (docs/07 § Text size).
    func learnerTextScale(_ app: AppModel) -> some View { modifier(LearnerTextScale(app: app)) }
}

/// Reads the setting in a view body, so a change redraws every `dsFont` below.
private struct LearnerTextScale: ViewModifier {
    let app: AppModel

    func body(content: Content) -> some View {
        content.environment(\.textScale, app.settings.textScale)
    }
}

/// The Mac's Lesson menu and View-menu items (installed by `ItalianoApp` on macOS only; the iPad keeps the in-view
/// keyboard shortcuts).
struct ItalianoCommands: Commands {
    let textSize: TextSizeController

    @FocusedValue(\.lessonCheck) private var check: LessonMenuAction?
    @FocusedValue(\.lessonShowHint) private var showHint: LessonMenuAction?
    @FocusedValue(\.lessonListenAgain) private var listenAgain: LessonMenuAction?
    @FocusedValue(\.lessonShowAnswer) private var showAnswer: LessonMenuAction?
    @FocusedValue(\.lessonClose) private var close: LessonMenuAction?
    @FocusedValue(\.showEnglish) private var showEnglish: Binding<Bool>?

    // The text-size items stay enabled (a command at either end changes nothing): a Commands body isn't
    // guaranteed to redraw when the setting changes, and a stale disabled item would block ⌘+.
    var body: some Commands {
        CommandMenu("Lesson") {
            Button("Check") { check?.perform() }
                .keyboardShortcut(.return, modifiers: [])
                .disabled(check == nil)
            Button("Show Hint") { showHint?.perform() }
                .keyboardShortcut("h", modifiers: [.command, .shift])
                .disabled(showHint == nil)
            Button("Listen Again") { listenAgain?.perform() }
                .keyboardShortcut("l", modifiers: .command)
                .disabled(listenAgain == nil)
            Button("Show Answer") { showAnswer?.perform() }
                .keyboardShortcut("a", modifiers: [.command, .shift])
                .disabled(showAnswer == nil)
            Divider()
            Button("Close Lesson") { close?.perform() }
                .keyboardShortcut(.escape, modifiers: [])
                .disabled(close == nil)
        }
        CommandGroup(after: .toolbar) {
            Button("Bigger Text") { textSize.apply(.bigger) }
                .keyboardShortcut("+", modifiers: .command)
            Button("Smaller Text") { textSize.apply(.smaller) }
                .keyboardShortcut("-", modifiers: .command)
            Button("Actual Size") { textSize.apply(.actualSize) }
                .keyboardShortcut("0", modifiers: .command)
            Divider()
            Toggle("Show English", isOn: showEnglish ?? .constant(false))
                .keyboardShortcut("e", modifiers: [.command, .shift])
                .disabled(showEnglish == nil)
        }
    }
}
