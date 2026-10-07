import Foundation
import Testing

@testable import Italiano

/// M6.10 (model): review-mode comments become the docs/04 review file. Runs on Linux too.
@MainActor
@Suite struct ReviewFileTests {
    let index = ReviewFileIndex(byPrefix: [
        "u02.l1": .init(file: "content/units/02-al-bar/lesson-1.yaml", hash: "aaa"),
        "u02.task": .init(file: "content/units/02-al-bar/task.yaml", hash: "bbb"),
        "w:cornetto": .init(file: "content/items/u02.yaml", hash: "ccc"),
    ])

    func collector() -> ReviewCollector {
        var n = 0
        return ReviewCollector(reviewer: "Teacher", scope: "u02", index: index, newID: { n += 1; return "c\(n)" },
                               nowISO: { "2026-10-20T09:15:00Z" })
    }

    @Test func targetsResolveToTheirFiles() {
        #expect(index.entry(for: "u02.l1.ex07")?.file == "content/units/02-al-bar/lesson-1.yaml")
        #expect(index.entry(for: "u02.l1.story#3")?.hash == "aaa")
        #expect(index.entry(for: "u02.task.conv1/n3")?.file == "content/units/02-al-bar/task.yaml")
        #expect(index.entry(for: "w:cornetto")?.hash == "ccc")
        #expect(index.entry(for: "u05.l1.ex01") == nil)
    }

    @Test func shouldBeAcceptedFilesAnAnswerKeyComment() throws {
        let c = collector()
        c.shouldBeAccepted(exerciseID: "u02.l1.ex07", turnID: nil, response: "quanto viene?", prompt: "How much is it?")
        c.add(target: "u02.task.conv1/n2", quote: "Certo. E da mangiare?", verdict: .question, category: .naturalness,
              comment: "Would Giulia say this?", suggestion: "")
        let file = c.reviewFile()
        #expect(file.format == 1 && file.channel == "app" && file.scope == "u02")
        #expect(file.files == ["content/units/02-al-bar/lesson-1.yaml": "aaa", "content/units/02-al-bar/task.yaml": "bbb"])
        #expect(file.comments[0].category == .answerKey && file.comments[0].response == "quanto viene?")
        #expect(file.comments[1].suggestion == nil)
        #expect(file.suggestedFileName == "review-u02-2026-10-20.json")
        let json = try JSONSerialization.jsonObject(with: file.encoded()) as? [String: Any]
        #expect(json?["signoff"] == nil || json?["signoff"] is NSNull)
        #expect((json?["comments"] as? [[String: Any]])?.first?["target"] as? String == "u02.l1.ex07")
    }

    @Test func indexFromPackMeta() {
        let i = ReviewFileIndex(metaJSON: #"{"u02.check":{"file":"content/units/02-al-bar/check.yaml","hash":"h"}}"#)
        #expect(i.entry(for: "u02.check.07")?.file == "content/units/02-al-bar/check.yaml")
        #expect(ReviewFileIndex(metaJSON: nil).byPrefix.isEmpty)
    }
}
