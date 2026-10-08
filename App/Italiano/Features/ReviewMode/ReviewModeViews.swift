import LearningCore
import SwiftUI

// Review mode's screens (docs/04 § Review mode in the app, docs/06 § Shared player behaviour, task M6.10): the
// review bar in the player, the comment sheet, the answer key, "This should be accepted" in the feedback panel,
// the jump menu and the comments screen with Send and Export. Thin views over `ReviewMode` (platform-neutral,
// tested on Linux). Nothing here is shown unless `ReviewMode.isActive` (Review and Debug builds, dev pack).

// MARK: - Environment

/// "Comment" from a long-press on a story line or a word card; nil outside review mode.
struct ReviewCommentAction {
    let perform: (ReviewTarget) -> Void
}

/// "This should be accepted" for the feedback panel; nil unless the exercise on screen has a rejected answer.
struct ReviewAcceptAction {
    let isFiled: Bool
    let perform: () -> Void
}

private struct ReviewCommentKey: EnvironmentKey {
    static var defaultValue: ReviewCommentAction? { nil }
}

private struct ReviewAcceptKey: EnvironmentKey {
    static var defaultValue: ReviewAcceptAction? { nil }
}

extension EnvironmentValues {
    var reviewComment: ReviewCommentAction? {
        get { self[ReviewCommentKey.self] }
        set { self[ReviewCommentKey.self] = newValue }
    }

    var reviewAccept: ReviewAcceptAction? {
        get { self[ReviewAcceptKey.self] }
        set { self[ReviewAcceptKey.self] = newValue }
    }
}

// MARK: - Long-press to comment

/// A story line or word card the content lead can comment on with a long-press (right-click on Mac) or the
/// VoiceOver action; does nothing for learners.
struct ReviewCommentable: ViewModifier {
    let target: ReviewTarget
    @Environment(\.reviewComment) private var comment

    func body(content: Content) -> some View {
        if let comment {
            content
                .contextMenu {
                    Button("Comment", systemImage: "text.bubble") { comment.perform(target) }
                        .accessibilityIdentifier("review.comment.menu")
                }
                .accessibilityAction(named: Text("Comment")) { comment.perform(target) }
        } else {
            content
        }
    }
}

extension View {
    func reviewCommentable(_ target: ReviewTarget) -> some View { modifier(ReviewCommentable(target: target)) }
}

// MARK: - "This should be accepted"

/// Under the feedback panel's buttons after a rejected answer (review mode only).
struct ReviewShouldAcceptButton: View {
    let action: ReviewAcceptAction

    var body: some View {
        Button(
            action.isFiled ? "Filed: should be accepted" : "This should be accepted",
            systemImage: action.isFiled ? "checkmark" : "checkmark.bubble", action: action.perform
        )
        .buttonStyle(.dsSecondarySmall)
        .disabled(action.isFiled)
        .accessibilityLabel(Text(action.isFiled ? "Filed: this should be accepted" : "This should be accepted"))
        .accessibilityIdentifier("review.shouldAccept")
    }
}

// MARK: - The player's review bar and sheets

enum ReviewSheet: Identifiable {
    case comment(ReviewTarget?)
    case key(ExerciseID)

    var id: String {
        switch self {
        case .comment(let t): "comment:\(t?.id ?? "")"
        case .key(let e): "key:\(e.rawValue)"
        }
    }
}

/// Adds the review bar (Previous, Next, draft badge, Answer key, Comment), the long-press comment action, "This
/// should be accepted" and their sheets to the lesson player. With `review == nil` it changes nothing.
struct ReviewPlayerTools: ViewModifier {
    let review: ReviewMode?
    let model: LessonPlayerModel
    /// The exercise model on screen (a conversation's current turn is a target).
    let host: ExerciseHostModel?
    let move: (Int) -> Void
    @State private var sheet: ReviewSheet?

    func body(content: Content) -> some View {
        if let review, review.isActive {
            content
                .safeAreaInset(edge: .bottom, spacing: 0) { bar(review) }
                .environment(\.reviewComment, ReviewCommentAction { sheet = .comment($0) })
                .environment(\.reviewAccept, acceptAction(review))
                .sheet(item: $sheet) { s in
                    switch s {
                    case .comment(let first):
                        ReviewCommentSheet(
                            review: review, draft: review.commentDraft(targets: targets(review, first)),
                            onDone: { sheet = nil })
                    case .key(let id):
                        AnswerKeySheet(key: model.bundle.exercises[id].map { AnswerKey($0) }, onDone: { sheet = nil })
                    }
                }
        } else {
            content
        }
    }

    private var exerciseID: ExerciseID? {
        if case .exercise(let id)? = model.current?.page { return id }
        return nil
    }

    private var conversationNode: String? {
        if case .conversation(let m)? = host, !m.isFinished { return m.nodeID }
        return nil
    }

    private func targets(_ review: ReviewMode, _ first: ReviewTarget?) -> [ReviewTarget] {
        guard let entry = model.current else { return [first].compactMap { $0 } }
        return review.targets(for: entry, bundle: model.bundle, conversationNode: conversationNode, first: first)
    }

    private func acceptAction(_ review: ReviewMode) -> ReviewAcceptAction? {
        guard let id = exerciseID, let rejected = review.rejectedAnswer(for: id),
            review.collector.canFile(rejected.target)
        else { return nil }
        let payload = model.bundle.exercises[id]
        return ReviewAcceptAction(isFiled: review.isFiled(rejected)) {
            review.fileAcceptRequest(rejected, payload: payload)
        }
    }

    private func bar(_ review: ReviewMode) -> some View {
        HStack(spacing: Tokens.Space.s) {
            Button {
                move(model.position - 1)
            } label: {
                Image(systemName: "chevron.left").frame(width: Tokens.Size.minTouch, height: Tokens.Size.minTouch)
            }
            .disabled(model.position == 0)
            .keyboardShortcut("[", modifiers: .command)
            .accessibilityLabel(Text("Previous page"))
            .accessibilityIdentifier("review.prev")
            Button {
                move(model.position + 1)
            } label: {
                Image(systemName: "chevron.right").frame(width: Tokens.Size.minTouch, height: Tokens.Size.minTouch)
            }
            .disabled(model.isFinished)
            .keyboardShortcut("]", modifiers: .command)
            .accessibilityLabel(Text("Next page"))
            .accessibilityIdentifier("review.next")
            if let step = model.currentStep, review.isDraft(step.id) { DraftBadge() }
            Spacer(minLength: Tokens.Space.s)
            if let id = exerciseID {
                Button("Answer key", systemImage: "key") { sheet = .key(id) }
                    .buttonStyle(.dsSecondarySmall)
                    .keyboardShortcut("k", modifiers: [.command, .shift])
                    .accessibilityIdentifier("review.key")
            }
            Button("Comment", systemImage: "text.bubble") { sheet = .comment(nil) }
                .buttonStyle(.dsSecondarySmall)
                .keyboardShortcut("c", modifiers: [.command, .shift])
                .accessibilityIdentifier("review.comment")
        }
        .buttonStyle(.plain)
        .foregroundStyle(Color.ds.ink)
        .padding(.horizontal, Tokens.Space.l)
        .padding(.vertical, Tokens.Space.xs)
        .background(Color.ds.surface)
        .overlay(alignment: .top) { Divider() }
    }
}

/// "Draft": the step's file isn't approved yet (dev packs only).
struct DraftBadge: View {
    var body: some View {
        Text("Draft")
            .dsFont(Tokens.TypeScale.uiCaption)
            .foregroundStyle(Color.ds.warningText)
            .padding(.horizontal, Tokens.Space.s)
            .padding(.vertical, Tokens.Space.xxs)
            .background(Capsule().fill(Color.ds.warningBackground))
            .accessibilityLabel(Text("Draft, not approved yet"))
            .accessibilityIdentifier("review.draft")
    }
}

// MARK: - Comment sheet

/// Pre-filled with the target, its quoted text and the file and hash it will be filed against; the content lead
/// adds the verdict, category, comment and a suggestion.
struct ReviewCommentSheet: View {
    let review: ReviewMode
    @State private var draft: ReviewCommentDraft
    @State private var name = ""
    let onDone: () -> Void

    init(review: ReviewMode, draft: ReviewCommentDraft, onDone: @escaping () -> Void) {
        self.review = review
        _draft = State(initialValue: draft)
        self.onDone = onDone
    }

    private var needsName: Bool {
        review.collector.reviewer.isEmpty && name.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if draft.targets.isEmpty {
                        Text("Nothing here can be filed: the course pack doesn't name its file.")
                            .dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
                    } else {
                        Picker("Comment on", selection: $draft.selectedID) {
                            ForEach(draft.targets) { t in Text(t.label).tag(t.id) }
                        }
                        .accessibilityIdentifier("review.commentSheet.target")
                    }
                    if let t = draft.target {
                        Text(t.id).font(.footnote.monospaced()).foregroundStyle(Color.ds.secondary)
                            .textSelection(.enabled)
                        if let quote = t.quote {
                            Text(quote).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                        }
                        if let line = review.collector.fileLine(for: t.id) {
                            Text(line).font(.caption.monospaced()).foregroundStyle(Color.ds.secondary)
                        }
                    }
                } header: {
                    Text("What it's about")
                }
                Section {
                    Picker("Verdict", selection: $draft.verdict) {
                        ForEach(ReviewComment.Verdict.allCases, id: \.self) { v in Text(v.title).tag(v) }
                    }
                    .pickerStyle(.segmented)
                    .accessibilityIdentifier("review.commentSheet.verdict")
                    Picker("Category", selection: $draft.category) {
                        Text("Choose…").tag(ReviewComment.Category?.none)
                        ForEach(ReviewComment.Category.allCases, id: \.self) { c in
                            Text(c.label).tag(ReviewComment.Category?.some(c))
                        }
                    }
                    .accessibilityIdentifier("review.commentSheet.category")
                    TextField("Comment", text: $draft.comment, axis: .vertical)
                        .lineLimit(3...10)
                        .accessibilityIdentifier("review.commentSheet.comment")
                    TextField("Suggested Italian (optional)", text: $draft.suggestion, axis: .vertical)
                        .lineLimit(1...4)
                        .accessibilityIdentifier("review.commentSheet.suggestion")
                } header: {
                    Text("Your comment")
                }
                if review.collector.reviewer.isEmpty {
                    Section {
                        TextField("Your name", text: $name)
                            .accessibilityIdentifier("review.commentSheet.name")
                    } header: {
                        Text("Who is reviewing")
                    }
                }
            }
            .navigationTitle("Comment")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel", action: onDone)
                        .accessibilityIdentifier("review.commentSheet.cancel")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        if !name.isEmpty { review.collector.setReviewer(name) }
                        if review.save(draft) != nil { onDone() }
                    }
                    .disabled(!draft.canSave || needsName)
                    .accessibilityIdentifier("review.commentSheet.save")
                }
            }
        }
        .accessibilityIdentifier("review.commentSheet")
    }
}

// MARK: - Answer key

struct AnswerKeySheet: View {
    let key: AnswerKey?
    let onDone: () -> Void

    var body: some View {
        NavigationStack {
            List {
                if let key {
                    ForEach(Array(key.sections.enumerated()), id: \.offset) { _, section in
                        Section {
                            ForEach(Array(section.entries.enumerated()), id: \.offset) { _, entry in
                                VStack(alignment: .leading, spacing: Tokens.Space.xxs) {
                                    if entry.isItalian {
                                        ItalianText(entry.text, style: Tokens.TypeScale.italianBody)
                                    } else {
                                        Text(entry.text).dsFont(Tokens.TypeScale.uiBody)
                                    }
                                    if let note = entry.note {
                                        Text(note).dsFont(Tokens.TypeScale.uiCaption)
                                            .foregroundStyle(Color.ds.secondary)
                                    }
                                }
                                .accessibilityElement(children: .combine)
                            }
                        } header: {
                            Text(section.title)
                        } footer: {
                            if let caption = section.caption { Text(caption).font(.caption.monospaced()) }
                        }
                    }
                } else {
                    Text("This exercise isn't in the course pack.")
                }
            }
            .navigationTitle(key.map { "Answer key · \($0.exerciseID.rawValue)" } ?? "Answer key")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done", action: onDone).accessibilityIdentifier("review.keySheet.done")
                }
            }
        }
        .accessibilityIdentifier("review.keySheet")
    }
}

// MARK: - Course: jump menu and comments

/// The Course tab's review tools: **Jump to** (`review.jump`) and **Review comments** (`review.comments`, with
/// Send and Export). With review mode off it changes nothing.
struct ReviewCourseTools: ViewModifier {
    let review: ReviewMode?
    let onJump: (ReviewJump) -> Void
    @State private var showJump = false
    @State private var showComments = false
    @State private var pending: ReviewJump?

    func body(content: Content) -> some View {
        if let review, review.isActive {
            content
                .toolbar {
                    ToolbarItemGroup(placement: .primaryAction) {
                        Button("Jump to", systemImage: "arrow.forward.circle") { showJump = true }
                            .accessibilityIdentifier("review.jump")
                        Button("Review comments (\(review.collector.filed.count))", systemImage: "text.bubble") {
                            showComments = true
                        }
                        .accessibilityIdentifier("review.comments")
                    }
                }
                // The player opens after the sheet is gone (two presentations can't overlap).
                .sheet(
                    isPresented: $showJump,
                    onDismiss: {
                        if let jump = pending {
                            pending = nil
                            onJump(jump)
                        }
                    }
                ) {
                    ReviewJumpSheet(
                        menu: review.menu,
                        onPick: {
                            pending = $0
                            showJump = false
                        }, onDone: { showJump = false })
                }
                .sheet(isPresented: $showComments) {
                    ReviewCommentsScreen(review: review) { showComments = false }
                }
        } else {
            content
        }
    }
}

/// Every unit, lesson and step, unlocked, with draft badges; search by ID or title (`u02.l1.ex07`).
struct ReviewJumpSheet: View {
    let menu: ReviewJumpMenu
    let onPick: (ReviewJump) -> Void
    let onDone: () -> Void
    @State private var query = ""

    var body: some View {
        NavigationStack {
            List {
                if query.trimmingCharacters(in: .whitespaces).isEmpty {
                    ForEach(menu.units) { unit in
                        Section {
                            ForEach(unit.groups) { group in
                                ForEach(group.steps) { step in
                                    NavigationLink(value: step) {
                                        row(group.title, step.title, isDraft: step.isDraft)
                                    }
                                    .accessibilityIdentifier("review.jump.\(step.id.rawValue)")
                                }
                            }
                        } header: {
                            Text(unit.title)
                        }
                    }
                } else {
                    ForEach(menu.search(query)) { hit in
                        Button {
                            onPick(hit.jump)
                        } label: {
                            row(hit.jump.exercise?.rawValue ?? hit.jump.step.rawValue, hit.title, isDraft: hit.isDraft)
                        }
                        .accessibilityIdentifier("review.jump.\(hit.id)")
                    }
                }
            }
            .searchable(text: $query, prompt: "Step or exercise ID, or a title")
            .navigationTitle("Jump to")
            .navigationDestination(for: ReviewJumpMenu.Step.self) { step in
                List {
                    Button("From the start of this step") { onPick(ReviewJump(step: step.id)) }
                        .accessibilityIdentifier("review.jump.\(step.id.rawValue).start")
                    ForEach(step.exercises, id: \.self) { ex in
                        Button(ex.rawValue) { onPick(ReviewJump(step: step.id, exercise: ex)) }
                            .font(.body.monospaced())
                            .accessibilityIdentifier("review.jump.\(ex.rawValue)")
                    }
                }
                .navigationTitle(step.title)
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close", action: onDone).accessibilityIdentifier("review.jump.close")
                }
            }
        }
    }

    private func row(_ caption: String, _ title: String, isDraft: Bool) -> some View {
        HStack(spacing: Tokens.Space.m) {
            VStack(alignment: .leading, spacing: Tokens.Space.xxs) {
                Text(title).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                Text(caption).font(.caption.monospaced()).foregroundStyle(Color.ds.secondary)
            }
            Spacer(minLength: Tokens.Space.s)
            if isDraft { DraftBadge() }
        }
    }
}

/// The comments made so far, the reviewer's name, **Send** (when the build has the review endpoint and token) and
/// **Export** (the share sheet with the review files `content review-import` takes).
struct ReviewCommentsScreen: View {
    let review: ReviewMode
    let onDone: () -> Void
    @State private var exportURLs: [URL] = []
    @State private var exportError: String?
    @State private var name = ""

    private var collector: ReviewCollector { review.collector }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TextField("Your name", text: $name)
                        .onAppear { name = collector.reviewer }
                        .onChange(of: name) { _, new in collector.setReviewer(new) }
                        .accessibilityIdentifier("review.name")
                } header: {
                    Text("Reviewer")
                }
                Section {
                    if review.canSend {
                        Button("Send \(collector.unsent.count) comment\(collector.unsent.count == 1 ? "" : "s")") {
                            Task { await review.send() }
                        }
                        .disabled(
                            collector.unsent.isEmpty || review.sendState == .sending || collector.reviewer.isEmpty
                        )
                        .accessibilityIdentifier("review.send")
                    } else {
                        Text("Sending isn't set up in this build. Use Export and send the file by email.")
                            .dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                    }
                    ShareLink(items: exportURLs) {
                        Label("Export the review file", systemImage: "square.and.arrow.up")
                    }
                    .disabled(exportURLs.isEmpty || collector.reviewer.isEmpty)
                    .accessibilityIdentifier("review.export")
                    if let status = review.sendStatus {
                        Text(status).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                            .accessibilityIdentifier("review.sendStatus")
                    }
                    if let error = collector.saveError ?? collector.loadError ?? exportError {
                        Text(error).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.warningText)
                    }
                }
                Section {
                    if collector.filed.isEmpty {
                        Text("No comments yet. Use Comment in a lesson, or long-press a story line or word.")
                            .dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                    }
                    ForEach(collector.filed, id: \.comment.id) { f in
                        VStack(alignment: .leading, spacing: Tokens.Space.xxs) {
                            Text("\(f.comment.target) · \(f.comment.verdict.title) · \(f.comment.category.label)")
                                .font(.caption.monospaced()).foregroundStyle(Color.ds.secondary)
                            if !f.comment.comment.isEmpty {
                                Text(f.comment.comment).dsFont(Tokens.TypeScale.uiBody)
                            }
                            if let s = f.comment.suggestion ?? f.comment.response {
                                ItalianText(s, style: Tokens.TypeScale.italianBody)
                            }
                            if f.sent {
                                Text("Sent").dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.success)
                            }
                        }
                        .accessibilityElement(children: .combine)
                        .deleteDisabled(f.sent)
                    }
                    .onDelete { offsets in
                        let ids = offsets.compactMap { collector.filed[safe: $0]?.comment.id }
                        for id in ids { collector.remove(id: id) }
                    }
                } header: {
                    Text("Comments")
                }
            }
            .navigationTitle("Review comments")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done", action: onDone).accessibilityIdentifier("review.comments.done")
                }
            }
        }
        .task(id: "\(collector.filed.count)|\(collector.reviewer)") { writeExport() }
        .accessibilityIdentifier("review.commentsScreen")
    }

    /// The share sheet needs files up front: rewrite them whenever the comments or the name change.
    private func writeExport() {
        guard !collector.filed.isEmpty else {
            exportURLs = []
            return
        }
        do {
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(
                "review-export", isDirectory: true)
            try? FileManager.default.removeItem(at: folder)
            exportURLs = try review.exportFiles(to: folder)
            exportError = nil
        } catch {
            exportURLs = []
            exportError = "The review file couldn't be written. Try again."
        }
    }
}
