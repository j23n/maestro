import Foundation
import SwiftData
import Testing
import ItalianCore
import SRSKit
@testable import Maestro

@MainActor @Suite struct RememberStoreTests {
    let container = LearnerSchema.makeContainer(inMemory: true)
    let prefs = Preferences()

    var store: RememberStore { RememberStore(context: container.mainContext, prefs: prefs, content: nil) }

    func item() -> RememberItem {
        RememberItem.verbForm(lemmaID: "it:andare:v", formTag: "cond.pass.1p", surface: "saremmo andati")
            .inSentence(textID: "racconti-brevi-03", sentenceID: "s1", text: "Decise che saremmo andati a Bologna.",
                        translation: "He decided we would go to Bologna.",
                        ranges: [UTF16Range(start: 11, length: 7), UTF16Range(start: 19, length: 6)])
    }

    @Test func keepDeleteAndRestoreKeepOneCard() throws {
        let item = item()
        store.toggle(item)
        #expect(store.isKept(item.key))
        let card = try #require(store.cards(for: item.key).first)
        #expect(card.highlightRanges == "11:7,19:6")
        #expect(card.kind == "verbForm")

        store.toggle(item)
        #expect(!store.isKept(item.key))
        store.toggle(item)
        #expect(store.isKept(item.key))
        #expect(store.cards(for: item.key).count == 1)
    }

    @Test func reviewWritesALogAndASchedule() throws {
        let item = item()
        store.toggle(item)
        let card = try #require(store.cards(for: item.key).first)
        store.review(card, rating: .good, durationMs: 1200)
        #expect(store.logs(for: item.key).count == 1)
        let schedule = try #require(store.schedule(for: item.key))
        #expect(schedule.reps == 1)
        #expect(schedule.due > .now)
    }

    @Test func newItemsAreQueuedUpToTheDailyLimit() {
        prefs.newItemsPerDay = 1
        store.toggle(item())
        store.toggle(.grammar("future-in-the-past", surface: "saremmo andati"))
        #expect(store.queue().count == 1)
        prefs.newItemsPerDay = 10
    }

    @Test func mergePassLeavesCardsWithUnknownIDsAlone() {
        let context = container.mainContext
        for _ in 0..<2 {
            context.insert(Card(itemKey: "word|it:nuovo:adj|it:nuovo:adj#zzzz", kind: "word"))
        }
        try? context.save()
        store.mergePass()
        #expect(store.cards(for: "word|it:nuovo:adj|it:nuovo:adj#zzzz").count == 2)
    }

    @Test func answersAreRecorded() throws {
        store.recordAnswer(textID: "t", questionID: "q1", choice: 2)
        let progress = try #require(store.progress(for: "t"))
        #expect(progress.answersJSON.contains("\"q1\""))
    }
}
