import Foundation
import Testing
@testable import SRSKit

@Suite struct FSRSTests {
    let scheduler = FSRSScheduler()
    let start = Date(timeIntervalSince1970: 1_767_268_800) // 2026-01-01 12:00 UTC

    @Test func firstReviewUsesInitialStabilityAndDifficulty() {
        let w = FSRSParameters.defaultWeights
        for rating in Rating.allCases {
            let s = scheduler.review(Schedule(), ReviewEvent(reviewedAt: start, rating: rating))
            #expect(abs(s.stability - w[rating.rawValue - 1]) < 1e-9)
            let d0 = min(max(w[4] - exp(w[5] * Double(rating.rawValue - 1)) + 1, 1), 10)
            #expect(abs(s.difficulty - d0) < 1e-9)
            #expect(s.reps == 1)
        }
    }

    @Test func learningStepsThenReview() {
        var s = scheduler.review(Schedule(), ReviewEvent(reviewedAt: start, rating: .good))
        #expect(s.state == .learning && s.step == 1)
        #expect(s.due == start.addingTimeInterval(600))
        s = scheduler.review(s, ReviewEvent(reviewedAt: s.due, rating: .good))
        #expect(s.state == .review)
        #expect(s.scheduledDays >= 1)
        let again = scheduler.review(Schedule(), ReviewEvent(reviewedAt: start, rating: .again))
        #expect(again.state == .learning && again.due == start.addingTimeInterval(60))
        let easy = scheduler.review(Schedule(), ReviewEvent(reviewedAt: start, rating: .easy))
        #expect(easy.state == .review)
    }

    @Test func lapseGoesToRelearning() {
        var s = scheduler.review(Schedule(), ReviewEvent(reviewedAt: start, rating: .easy))
        let before = s.stability
        s = scheduler.review(s, ReviewEvent(reviewedAt: s.due, rating: .again))
        #expect(s.state == .relearning)
        #expect(s.lapses == 1)
        #expect(s.stability < before)
    }

    @Test func intervalsGrowWithGoodReviews() {
        var s = scheduler.review(Schedule(), ReviewEvent(reviewedAt: start, rating: .easy))
        var last = s.scheduledDays
        for _ in 0..<4 {
            s = scheduler.review(s, ReviewEvent(reviewedAt: s.due, rating: .good))
            #expect(s.scheduledDays > last)
            last = s.scheduledDays
        }
    }

    @Test func intervalAtDesiredRetentionEqualsStability() {
        // With retention 0.9, R(S) = 0.9, so the interval is the stability rounded.
        #expect(scheduler.interval(for: 10) == 10)
        #expect(scheduler.interval(for: 0.2) == 1)
    }

    @Test func replayIsOrderIndependentAndDeterministic() {
        let events = [
            ReviewEvent(reviewedAt: start, rating: .good),
            ReviewEvent(reviewedAt: start.addingTimeInterval(600), rating: .good),
            ReviewEvent(reviewedAt: start.addingTimeInterval(86400 * 3), rating: .hard),
            ReviewEvent(reviewedAt: start.addingTimeInterval(86400 * 9), rating: .good),
        ]
        let a = scheduler.replay(events)
        let b = scheduler.replay(events.reversed())
        #expect(a == b)
        #expect(a.reps == 4)
    }

    @Test func dayRollsOverAtFourLocal() {
        // 03:30 and 04:30 local time (UTC+2) fall on different review days.
        let tz = 120
        let base = Date(timeIntervalSince1970: 1_767_225_600) // 2026-01-01 00:00 UTC = 02:00 local
        let early = base.addingTimeInterval(90 * 60)  // 03:30 local
        let late = base.addingTimeInterval(150 * 60)  // 04:30 local
        #expect(scheduler.dayNumber(late, tzOffsetMinutes: tz) == scheduler.dayNumber(early, tzOffsetMinutes: tz) + 1)
        let day = scheduler.dayNumber(late, tzOffsetMinutes: tz)
        #expect(scheduler.startOfDay(day, tzOffsetMinutes: tz) == base.addingTimeInterval(120 * 60))
    }

    @Test func queuePutsDueBeforeNewAndLimitsNew() {
        let due = Schedule(due: start.addingTimeInterval(-60))
        var reviewed = due
        reviewed.reps = 3
        let items: [ReviewQueue.Item<String>] = [
            .init(key: "new1", schedule: nil, createdAt: start),
            .init(key: "new2", schedule: nil, createdAt: start.addingTimeInterval(1)),
            .init(key: "due", schedule: reviewed, createdAt: start),
        ]
        #expect(ReviewQueue.build(items, now: start, newLimit: 1, newSeenToday: 0) == ["due", "new1"])
        #expect(ReviewQueue.build(items, now: start, newLimit: 1, newSeenToday: 1) == ["due"])
    }
}
