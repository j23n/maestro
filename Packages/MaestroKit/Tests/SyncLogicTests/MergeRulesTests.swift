import Foundation
import Testing
@testable import SyncLogic

@Suite struct MergeRulesTests {
    let t0 = Date(timeIntervalSince1970: 1_000_000)
    let known: Set<String> = ["it:andare:v", "it:andare:v#k3fq", "future-in-the-past"]
    let redirects = ["it:andare:v#old1": "it:andare:v#k3fq"]

    func resolve(_ id: String) -> String? {
        let r = redirects[id] ?? id
        return known.contains(r) ? r : nil
    }

    @Test func keepsOldestCard() {
        let a = MergeRules.CardSnapshot(id: UUID(), itemKey: "grammar|future-in-the-past", createdAt: t0.addingTimeInterval(10))
        let b = MergeRules.CardSnapshot(id: UUID(), itemKey: "grammar|future-in-the-past", createdAt: t0)
        let plan = MergeRules.planCards([a, b], resolve: resolve)
        #expect(plan.delete == [a.id])
        #expect(plan.reactivate.isEmpty)
    }

    @Test func tieGoesToSmallerUUID() {
        let x = UUID(uuidString: "00000000-0000-0000-0000-000000000001")!
        let y = UUID(uuidString: "00000000-0000-0000-0000-000000000002")!
        let plan = MergeRules.planCards([
            .init(id: y, itemKey: "grammar|future-in-the-past", createdAt: t0),
            .init(id: x, itemKey: "grammar|future-in-the-past", createdAt: t0),
        ], resolve: resolve)
        #expect(plan.delete == [y])
    }

    @Test func redirectedIDsAreDuplicates() {
        let old = MergeRules.CardSnapshot(id: UUID(), itemKey: "word|it:andare:v|it:andare:v#old1", createdAt: t0)
        let new = MergeRules.CardSnapshot(id: UUID(), itemKey: "word|it:andare:v|it:andare:v#k3fq", createdAt: t0.addingTimeInterval(5))
        let plan = MergeRules.planCards([old, new], resolve: resolve)
        #expect(plan.delete == [new.id])
    }

    @Test func survivorBecomesActiveIfAnyDuplicateWas() {
        let deleted = MergeRules.CardSnapshot(id: UUID(), itemKey: "grammar|future-in-the-past", createdAt: t0, deletedAt: t0.addingTimeInterval(100))
        let active = MergeRules.CardSnapshot(id: UUID(), itemKey: "grammar|future-in-the-past", createdAt: t0.addingTimeInterval(50))
        let plan = MergeRules.planCards([deleted, active], resolve: resolve)
        #expect(plan.delete == [active.id])
        #expect(plan.reactivate == [deleted.id])
    }

    @Test func unknownIDsAreLeftAlone() {
        let a = MergeRules.CardSnapshot(id: UUID(), itemKey: "word|it:nuovo:adj|it:nuovo:adj#zzzz", createdAt: t0)
        let b = MergeRules.CardSnapshot(id: UUID(), itemKey: "word|it:nuovo:adj|it:nuovo:adj#zzzz", createdAt: t0.addingTimeInterval(1))
        #expect(MergeRules.planCards([a, b], resolve: resolve).delete.isEmpty)
    }

    @Test func activity() {
        #expect(CardActivity.isActive(deletedAt: nil, restoredAt: nil))
        #expect(!CardActivity.isActive(deletedAt: t0, restoredAt: nil))
        #expect(CardActivity.isActive(deletedAt: t0, restoredAt: t0.addingTimeInterval(1)))
        #expect(!CardActivity.isActive(deletedAt: t0.addingTimeInterval(2), restoredAt: t0.addingTimeInterval(1)))
    }

    @Test func mergesTextProgress() throws {
        let old = MergeRules.ProgressSnapshot(
            id: UUID(), textID: "t", position: 0.2, maxFractionRead: 0.9, finishedAt: t0.addingTimeInterval(50),
            answers: ["q1": .init(choice: 0, at: t0), "q2": .init(choice: 1, at: t0.addingTimeInterval(9))],
            updatedAt: t0.addingTimeInterval(10), createdOrder: t0)
        let newer = MergeRules.ProgressSnapshot(
            id: UUID(), textID: "t", position: 0.5, maxFractionRead: 0.6, finishedAt: t0.addingTimeInterval(20),
            answers: ["q1": .init(choice: 2, at: t0.addingTimeInterval(5)), "q2": .init(choice: 0, at: t0.addingTimeInterval(1))],
            updatedAt: t0.addingTimeInterval(30), createdOrder: t0.addingTimeInterval(1))
        let merged = try #require(MergeRules.mergeProgress([newer, old]))
        #expect(merged.survivor.id == old.id)
        #expect(merged.delete == [newer.id])
        #expect(merged.survivor.position == 0.5)
        #expect(merged.survivor.maxFractionRead == 0.9)
        #expect(merged.survivor.finishedAt == t0.addingTimeInterval(20))
        #expect(merged.survivor.answers["q1"]?.choice == 2)
        #expect(merged.survivor.answers["q2"]?.choice == 1)
    }

    @Test func answersRoundTripJSON() {
        let answers = ["q1": MergeRules.Answer(choice: 1, at: Date(timeIntervalSince1970: 1_793_458_800))]
        let json = MergeRules.encodeAnswers(answers)
        #expect(MergeRules.decodeAnswers(json) == answers)
        #expect(MergeRules.decodeAnswers("").isEmpty)
    }

    @Test func trimsLookupsOldestFirst() {
        let entries = (0..<203).map { (id: UUID(), at: t0.addingTimeInterval(Double($0))) }
        let trimmed = MergeRules.trimLookups(entries)
        #expect(trimmed == entries.prefix(3).map(\.id))
    }
}
