import Foundation
import Testing

@testable import Italiano

/// M6.10 (model): review-mode comments become the docs/04 review file. Runs on Linux too.
@MainActor
@Suite struct ReviewFileTests {
    static let lessonHash = String(repeating: "a", count: 64)
    static let taskHash = String(repeating: "b", count: 64)
    static let itemsHash = String(repeating: "c", count: 64)
    static let specHash = String(repeating: "d", count: 64)

    let index = ReviewFileIndex(byPrefix: [
        "u02": .init(file: "content/units/02-al-bar/unit.yaml", hash: Self.specHash),
        "u02.l1": .init(file: "content/units/02-al-bar/lesson-1.yaml", hash: Self.lessonHash),
        "u02.task": .init(file: "content/units/02-al-bar/task.yaml", hash: Self.taskHash),
        "w:cornetto": .init(file: "content/items/u02.yaml", hash: Self.itemsHash),
    ])

    func collector(
        store: (any ReviewDraftStoring)? = nil, index: ReviewFileIndex? = nil, idPrefix: String = "c"
    ) -> ReviewCollector {
        var n = 0
        return ReviewCollector(
            index: index ?? self.index, store: store,
            newID: {
                n += 1
                return "\(idPrefix)\(n)"
            },
            nowISO: { "2026-10-20T09:15:00Z" })
    }

    @Test func targetsResolveToTheirFiles() {
        #expect(index.entry(for: "u02.l1.ex07")?.file == "content/units/02-al-bar/lesson-1.yaml")
        #expect(index.entry(for: "u02.l1.story#3")?.hash == Self.lessonHash)
        #expect(index.entry(for: "u02.task.conv1/n3")?.file == "content/units/02-al-bar/task.yaml")
        #expect(index.entry(for: "w:cornetto")?.hash == Self.itemsHash)
        #expect(index.entry(for: "u02.step-opener")?.file == "content/units/02-al-bar/unit.yaml")
        #expect(index.entry(for: "u05.l1.ex01") == nil)
    }

    /// Mirrors `itcontent.review.unit_of_comment`, so each file lands in the ledger `review-import` would pick.
    @Test func scopesFollowTheFile() {
        #expect(ReviewScope.of(file: "content/units/02-al-bar/lesson-1.yaml") == "u02")
        #expect(ReviewScope.of(file: "content/units/02-al-bar/task.yaml") == "u02")
        #expect(ReviewScope.of(file: "content/units/12-in-viaggio/check.yaml") == "u12")
        #expect(ReviewScope.of(file: "content/items/u02.yaml") == "u02")
        #expect(ReviewScope.of(file: "content/units/02-al-bar/unit.yaml") == "specs")
        #expect(ReviewScope.of(file: "content/grammar/points.yaml") == "specs")
        #expect(ReviewScope.of(file: "content/story-bible.yaml") == "specs")
        #expect(ReviewScope.of(file: "content/assessments/placement.yaml") == "assessments")
        #expect(ReviewScope.of(file: "content/items/u2.yaml") == "specs")
    }

    @Test func shouldBeAcceptedFilesAnAnswerKeyComment() throws {
        let c = collector()
        c.shouldBeAccepted(target: "u02.l1.ex07", response: "quanto fa", quote: "How much is it?")
        c.add(
            target: "u02.task.conv1/n2", quote: "Certo. E da mangiare?", verdict: .question, category: .naturalness,
            comment: " Would Giulia say this? ", suggestion: "")
        #expect(c.hasAcceptRequest(target: "u02.l1.ex07", response: "quanto fa"))
        let files = c.reviewFiles()
        #expect(files.count == 1)
        let file = try #require(files.first)
        #expect(file.format == 1 && file.channel == "app" && file.scope == "u02")
        #expect(file.reviewer == "Content lead")  // until the teacher gives a name
        #expect(
            file.files == [
                "content/units/02-al-bar/lesson-1.yaml": Self.lessonHash,
                "content/units/02-al-bar/task.yaml": Self.taskHash,
            ])
        #expect(file.comments[0].category == .answerKey && file.comments[0].response == "quanto fa")
        #expect(file.comments[0].verdict == .change)
        #expect(file.comments[1].suggestion == nil && file.comments[1].comment == "Would Giulia say this?")
        #expect(file.suggestedFileName == "review-u02-2026-10-20.json")
        let json = try #require(try JSONSerialization.jsonObject(with: file.encoded()) as? [String: Any])
        #expect(json["signoff"] is NSNull)
        let first = try #require((json["comments"] as? [[String: Any]])?.first)
        #expect(first["target"] as? String == "u02.l1.ex07")
        #expect(first["suggestion"] is NSNull)  // optional fields are written as null, like the review page
        #expect(
            Set(first.keys) == [
                "id", "target", "file", "quote", "verdict", "category", "comment", "suggestion", "response", "at",
            ])
    }

    /// The review page writes an empty comment as `null` (an OK alone, a suggestion without words); so does the app,
    /// and both the file and the stored draft read it back as empty.
    @Test func anEmptyCommentIsWrittenAsNull() throws {
        let c = collector()
        c.add(target: "u02.l1.ex08", quote: nil, verdict: .ok, category: .english, comment: "  ")
        c.add(target: "u02.l1.ex07", quote: nil, verdict: .change, category: .level, comment: "Too early.")
        let file = try #require(c.reviewFiles().first { $0.scope == "u02" })
        let json = try #require(try JSONSerialization.jsonObject(with: file.encoded()) as? [String: Any])
        let comments = try #require(json["comments"] as? [[String: Any]])
        #expect(comments[0]["comment"] is NSNull)
        #expect(comments[1]["comment"] as? String == "Too early.")
        let back = try JSONDecoder().decode(ReviewFile.self, from: file.encoded())
        #expect(back.comments.map(\.comment) == ["", "Too early."])
        let draft = try JSONEncoder().encode(ReviewDraft(reviewer: "", comments: c.filed))
        #expect(try JSONDecoder().decode(ReviewDraft.self, from: draft).comments == c.filed)
    }

    /// No Application Support folder: nothing can be kept, and the comments screen says so from launch.
    @Test func aStoreThatCantBeCreatedIsReportedAtOnce() {
        struct NoFolder: Error {}
        let store = FileReviewDraftStore.orUnavailable { throw NoFolder() }
        let c = collector(store: store)
        #expect(c.saveError == ReviewCollector.saveErrorText && c.loadError == nil)
        c.add(target: "u02.l1.ex07", quote: nil, verdict: .change, category: .level, comment: "x")
        #expect(c.saveError != nil && c.comments.count == 1)  // still in memory: Export works
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("review-\(UUID().uuidString)")
        let file = FileReviewDraftStore.orUnavailable {
            FileReviewDraftStore(url: folder.appendingPathComponent("r.json"))
        }
        #expect(collector(store: file).saveError == nil)
    }

    @Test func aTargetWithoutAFileIsNotFiled() {
        let c = collector()
        #expect(!c.canFile("u05.l1.ex01"))
        #expect(c.add(target: "u05.l1.ex01", quote: nil, verdict: .change, category: .other, comment: "x") == nil)
        #expect(c.comments.isEmpty)
        #expect(c.fileLine(for: "u02.l1.ex07") == "content/units/02-al-bar/lesson-1.yaml · aaaaaaaa")
    }

    @Test func oneFilePerScopeAndPerFileVersion() throws {
        let store = InMemoryReviewDraftStore()
        let before = collector(store: store)
        before.add(target: "u02.l1.ex07", quote: nil, verdict: .change, category: .level, comment: "old text")
        before.add(target: "u02.step-opener", quote: nil, verdict: .question, category: .english, comment: "spec")
        // An app update ships a new version of the lesson; the next comment is on the new text.
        let newHash = String(repeating: "e", count: 64)
        var updated = index.byPrefix
        updated["u02.l1"] = .init(file: "content/units/02-al-bar/lesson-1.yaml", hash: newHash)
        let after = collector(store: store, index: ReviewFileIndex(byPrefix: updated), idPrefix: "d")
        after.add(target: "u02.l1.ex08", quote: nil, verdict: .change, category: .level, comment: "new text")
        after.add(target: "w:cornetto", quote: "il cornetto", verdict: .ok, category: .english, comment: "")
        let files = after.reviewFiles()
        #expect(files.map(\.scope) == ["specs", "u02", "u02"])
        #expect(files[0].files == ["content/units/02-al-bar/unit.yaml": Self.specHash])
        #expect(files[1].comments.map(\.comment) == ["old text", ""])
        #expect(files[1].files["content/units/02-al-bar/lesson-1.yaml"] == Self.lessonHash)
        #expect(files[2].comments.map(\.comment) == ["new text"])
        #expect(files[2].files == ["content/units/02-al-bar/lesson-1.yaml": newHash])
    }

    @Test func commentsSurviveARelaunch() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("review-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: folder) }
        let store = FileReviewDraftStore(url: folder.appendingPathComponent("Italiano/review-comments.json"))
        let first = collector(store: store)
        first.setReviewer("  Maria Rossi ")
        first.add(
            target: "u02.l1.story#3", quote: "Buongiorno.", verdict: .change, category: .naturalness, comment: "a")
        first.markSent(["c1"])
        first.add(target: "u02.l1.ex07", quote: nil, verdict: .question, category: .level, comment: "b")
        let again = collector(store: store)
        #expect(again.reviewer == "Maria Rossi")
        #expect(again.comments.map(\.comment) == ["a", "b"])
        #expect(again.isSent("c1") && !again.isSent("c2"))
        #expect(again.unsent.map(\.id) == ["c2"])
        again.remove(id: "c1")  // sent comments stay
        again.remove(id: "c2")
        #expect(collector(store: store).comments.map(\.id) == ["c1"])
    }

    @Test func anUnreadableDraftIsKeptAsideNotOverwritten() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("review-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: folder) }
        let url = folder.appendingPathComponent("review-comments.json")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try Data("{ not json".utf8).write(to: url)
        let c = collector(store: FileReviewDraftStore(url: url))
        #expect(c.loadError != nil && c.comments.isEmpty)
        c.add(target: "u02.l1.ex07", quote: nil, verdict: .change, category: .level, comment: "x")
        let aside = folder.appendingPathComponent("review-comments.unreadable.json")
        #expect(try String(contentsOf: aside, encoding: .utf8) == "{ not json")
        #expect(collector(store: FileReviewDraftStore(url: url)).comments.count == 1)
    }

    @Test func aFailedSaveIsReported() {
        let store = InMemoryReviewDraftStore()
        store.failsToSave = true
        let c = collector(store: store)
        c.add(target: "u02.l1.ex07", quote: nil, verdict: .change, category: .level, comment: "x")
        #expect(c.saveError != nil)
        #expect(c.comments.count == 1)  // still in memory: Export works
    }

    @Test func indexFromPackMeta() {
        let i = ReviewFileIndex(metaJSON: #"{"u02.check":{"file":"content/units/02-al-bar/check.yaml","hash":"h"}}"#)
        #expect(i.entry(for: "u02.check.07")?.file == "content/units/02-al-bar/check.yaml")
        #expect(ReviewFileIndex(metaJSON: nil).byPrefix.isEmpty)
    }
}
