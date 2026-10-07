import Foundation

/// The settings the planner reads (docs/08 § Settings), with the docs/05 constants.
public struct PlannerSettings: Hashable, Sendable {
    /// `review.dailyLimit`.
    public var dailyReviewLimit: Int
    /// `goal.daysPerWeek`.
    public var weeklyGoal: Int
    public var sessionTarget: Int
    public var catchUpPerDay: Int
    /// Used until the learner has review sessions of their own.
    public var defaultSecondsPerCard: Double
    /// Above this many due cards, Review is the primary action.
    public var reviewPrimaryThreshold: Int

    public init(dailyReviewLimit: Int = 60, weeklyGoal: Int = 5, sessionTarget: Int = 20, catchUpPerDay: Int = 15,
                defaultSecondsPerCard: Double = 18, reviewPrimaryThreshold: Int = 40)
    {
        self.dailyReviewLimit = dailyReviewLimit
        self.weeklyGoal = weeklyGoal
        self.sessionTarget = sessionTarget
        self.catchUpPerDay = catchUpPerDay
        self.defaultSecondsPerCard = defaultSecondsPerCard
        self.reviewPrimaryThreshold = reviewPrimaryThreshold
    }

    public init(_ settings: LearnerSettings) {
        self.init(dailyReviewLimit: settings.reviewDailyLimit, weeklyGoal: settings.goalDaysPerWeek)
    }
}

/// What the Today screen shows (docs/05 § The Today planner).
public struct TodayPlan: Hashable, Sendable {
    public struct Review: Hashable, Sendable {
        /// Due pairs with a card, capped at what is left of today's review limit.
        public var dueCount: Int
        /// Due pairs with a card, uncapped.
        public var dueTotal: Int
        /// Active focus items with a card (reviewed first, on top of the due count).
        public var focusCount: Int
        /// dueCount × the learner's median seconds per card, in whole minutes (rounded up).
        public var estimatedMinutes: Int
        public var secondsPerCard: Double
        /// Two example items, in session order.
        public var exampleItems: [ItemID]

        public init(dueCount: Int, dueTotal: Int, focusCount: Int, estimatedMinutes: Int, secondsPerCard: Double,
                    exampleItems: [ItemID])
        {
            self.dueCount = dueCount
            self.dueTotal = dueTotal
            self.focusCount = focusCount
            self.estimatedMinutes = estimatedMinutes
            self.secondsPerCard = secondsPerCard
            self.exampleItems = exampleItems
        }
    }

    public struct CatchUp: Hashable, Sendable {
        /// New catch-up cards available today (at most 15 a day).
        public var count: Int
        /// Placement-introduced pairs still without memory.
        public var waiting: Int

        public init(count: Int, waiting: Int) {
            self.count = count
            self.waiting = waiting
        }
    }

    public struct Stats: Hashable, Sendable {
        public var wordsKnown: Int
        public var unitsCompleted: Int
        /// Units 0–12: 13 in the full course.
        public var unitsTotal: Int

        public init(wordsKnown: Int, unitsCompleted: Int, unitsTotal: Int) {
            self.wordsKnown = wordsKnown
            self.unitsCompleted = unitsCompleted
            self.unitsTotal = unitsTotal
        }
    }

    public var review: Review
    public var catchUp: CatchUp
    /// The first incomplete step in the earliest available unit.
    public var continuePoint: ContinuePoint?
    public var week: WeekProgress
    public var stats: Stats
    /// Due > 40: the Review card is the primary action. Lessons are never blocked.
    public var reviewIsPrimary: Bool

    /// For previews and App tests; the planner builds real plans.
    public init(review: Review, catchUp: CatchUp, continuePoint: ContinuePoint?, week: WeekProgress, stats: Stats,
                reviewIsPrimary: Bool)
    {
        self.review = review
        self.catchUp = catchUp
        self.continuePoint = continuePoint
        self.week = week
        self.stats = stats
        self.reviewIsPrimary = reviewIsPrimary
    }
}

/// `Planner.today(now:)` (docs/05 § The Today planner).
public struct Planner: Sendable {
    public let content: ContentIndex
    public let state: LearnerState
    public let device: DeviceCapabilities
    public let settings: PlannerSettings

    public init(content: ContentIndex, state: LearnerState, device: DeviceCapabilities = DeviceCapabilities(),
                settings: PlannerSettings = PlannerSettings())
    {
        self.content = content
        self.state = state
        self.device = device
        self.settings = settings
    }

    /// The session builder with this planner's settings.
    public var sessionBuilder: ReviewSessionBuilder {
        ReviewSessionBuilder(content: content, state: state, device: device, sessionTarget: settings.sessionTarget,
                             dailyLimit: settings.dailyReviewLimit, catchUpPerDay: settings.catchUpPerDay)
    }

    public func today(clock: any Clock) -> TodayPlan {
        today(now: clock.nowMs(), tzOffsetMinutes: clock.tzOffsetMinutes())
    }

    public func today(now: Int64, tzOffsetMinutes: Int) -> TodayPlan {
        let builder = sessionBuilder
        let ordered = builder.orderedPairs(now: now, tzOffsetMinutes: tzOffsetMinutes)
        let dueTotal = ordered.filter { $0.source == .due }.count
        let focusCount = ordered.filter { $0.source == .focus }.count
        let dueCount = min(dueTotal, builder.remainingDailyAllowance(now: now, tzOffsetMinutes: tzOffsetMinutes))
        let secondsPerCard = Self.median(state.secondsPerCardSamples) ?? settings.defaultSecondsPerCard
        let minutes = Int((Double(dueCount) * secondsPerCard / 60).rounded(.up))
        let review = TodayPlan.Review(
            dueCount: dueCount, dueTotal: dueTotal, focusCount: focusCount, estimatedMinutes: minutes,
            secondsPerCard: secondsPerCard, exampleItems: Array(ordered.prefix(2).map(\.pair.itemId)))

        let waiting = builder.catchUpPairs(now: now)
        let catchUp = TodayPlan.CatchUp(
            count: min(waiting.count, builder.catchUpAllowance(now: now, tzOffsetMinutes: tzOffsetMinutes)),
            waiting: waiting.count)

        let stats = TodayPlan.Stats(
            wordsKnown: Progress.wordsKnown(state: state, content: content, now: now),
            unitsCompleted: Progression.unitsCompleted(state: state, content: content),
            unitsTotal: content.courseUnits.count)

        return TodayPlan(
            review: review, catchUp: catchUp,
            continuePoint: Progression.continuePoint(state: state, content: content),
            week: Progress.week(state: state, now: now, tzOffsetMinutes: tzOffsetMinutes, goal: settings.weeklyGoal),
            stats: stats, reviewIsPrimary: dueCount > settings.reviewPrimaryThreshold)
    }

    /// The median of the samples, or nil when there are none.
    public static func median(_ samples: [Double]) -> Double? {
        guard !samples.isEmpty else { return nil }
        let sorted = samples.sorted()
        let mid = sorted.count / 2
        return sorted.count % 2 == 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
    }
}
