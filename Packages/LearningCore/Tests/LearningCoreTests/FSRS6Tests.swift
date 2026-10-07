import Foundation
import Testing

@testable import LearningCore

/// docs/05 § FSRS-6: every scenario in fixtures/fsrs/fsrs6-reference.json (py-fsrs 6.3.2) with relative tolerance
/// 1e-9 for stability, difficulty and retrievability, and exact due dates.
@Suite struct FSRS6Tests {
    struct Review: Decodable {
        let at: String
        let rating: Int
        let elapsedDaysBefore: Int?
        let retrievabilityBefore: Double?
        let stability: Double
        let difficulty: Double
        let intervalRaw: Double
        let due: String
    }

    struct Scenario: Decodable {
        let name: String
        let reviews: [Review]
    }

    struct Reference: Decodable {
        struct Config: Decodable {
            let parameters: [Double]
            let desiredRetention: Double
            let maximumInterval: Int64
        }

        let config: Config
        let scenarios: [Scenario]
    }

    static func reference() throws -> Reference {
        try JSONDecoder().decode(Reference.self, from: Fixtures.data("fixtures/fsrs/fsrs6-reference.json"))
    }

    static func close(_ a: Double, _ b: Double, rel: Double = 1e-9) -> Bool {
        if a == b { return true }
        return abs(a - b) <= rel * max(abs(a), abs(b))
    }

    @Test func configMatchesTheSpec() throws {
        let ref = try Self.reference()
        #expect(ref.config.parameters == FSRS6.defaultParameters)
        #expect(ref.config.desiredRetention == 0.9)
        #expect(ref.config.maximumInterval == 36_500)
        #expect(ref.scenarios.count == 35)
        #expect(ref.scenarios.reduce(0) { $0 + $1.reviews.count } == 317)
    }

    @Test func everyScenarioMatchesPyFSRS() throws {
        let ref = try Self.reference()
        let fsrs = FSRS6()
        var checked = 0
        for scenario in ref.scenarios {
            var state: MemoryState?
            for (i, step) in scenario.reviews.enumerated() {
                let at = Fixtures.ms(step.at)
                let label = "\(scenario.name) #\(i)"
                if let prev = state {
                    let t = FSRS6.elapsedDays(fromMs: prev.lastReviewMs, toMs: at)
                    #expect(Int(t) == step.elapsedDaysBefore, "\(label) elapsed days")
                    if let r = step.retrievabilityBefore {
                        #expect(Self.close(fsrs.retrievability(prev, atMs: at), r), "\(label) retrievability")
                    }
                }
                guard let rating = FSRSRating(rawValue: step.rating) else {
                    Issue.record("\(label): bad rating")
                    return
                }
                let next = fsrs.review(state, rating: rating, atMs: at)
                #expect(Self.close(next.stability, step.stability), "\(label) stability \(next.stability)")
                #expect(Self.close(next.difficulty, step.difficulty), "\(label) difficulty \(next.difficulty)")
                #expect(Self.close(fsrs.rawInterval(stability: next.stability), step.intervalRaw), "\(label) interval")
                #expect(next.dueMs == Fixtures.ms(step.due), "\(label) due")
                state = next
                checked += 1
            }
        }
        #expect(checked == 317)
    }

    @Test func roundHalfEvenMatchesPython() {
        #expect(FSRS6.roundHalfEven(0.5) == 0)
        #expect(FSRS6.roundHalfEven(1.5) == 2)
        #expect(FSRS6.roundHalfEven(2.5) == 2)
        #expect(FSRS6.roundHalfEven(3.5) == 4)
        #expect(FSRS6.roundHalfEven(2.4999) == 2)
        #expect(FSRS6.roundHalfEven(2.5001) == 3)
    }

    @Test func intervalIsClampedToOneDayAndTheMaximum() {
        let fsrs = FSRS6()
        #expect(fsrs.intervalDays(stability: 0.001) == 1)
        #expect(fsrs.intervalDays(stability: 1e9) == 36_500)
    }

    @Test func repsAndLapses() {
        let fsrs = FSRS6()
        var s = fsrs.review(nil, rating: .again, atMs: 0)
        #expect(s.reps == 1 && s.lapses == 0)  // the first review is never a lapse
        s = fsrs.review(s, rating: .again, atMs: 2 * FSRS6.msPerDay)
        s = fsrs.review(s, rating: .good, atMs: 4 * FSRS6.msPerDay)
        #expect(s.reps == 3 && s.lapses == 1)
    }
}
