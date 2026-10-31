import Foundation

public enum Rating: Int, Codable, Sendable, CaseIterable, Comparable {
    case again = 1, hard = 2, good = 3, easy = 4

    public var label: String {
        switch self {
        case .again: "Again"
        case .hard: "Hard"
        case .good: "Good"
        case .easy: "Easy"
        }
    }

    public static func < (a: Rating, b: Rating) -> Bool { a.rawValue < b.rawValue }
}

public enum LearningState: Int, Codable, Sendable {
    case new = 0, learning = 1, review = 2, relearning = 3
}

/// One review, as read from a synced ReviewLog.
public struct ReviewEvent: Sendable, Hashable {
    public var id: UUID
    public var reviewedAt: Date
    public var tzOffsetMinutes: Int
    public var rating: Rating

    public init(id: UUID = UUID(), reviewedAt: Date, tzOffsetMinutes: Int = 0, rating: Rating) {
        self.id = id
        self.reviewedAt = reviewedAt
        self.tzOffsetMinutes = tzOffsetMinutes
        self.rating = rating
    }
}

/// The per-item schedule. Mirrors the local-only ScheduleState model (HANDOFF.md 5.1).
public struct Schedule: Sendable, Hashable, Codable {
    public var state: LearningState = .new
    public var step: Int = 0
    public var stability: Double = 0
    public var difficulty: Double = 0
    public var reps: Int = 0
    public var lapses: Int = 0
    public var scheduledDays: Int = 0
    public var lastReviewedAt: Date? = nil
    public var lastTZOffsetMinutes: Int = 0
    public var due: Date

    public init(due: Date = Date(timeIntervalSince1970: 0)) {
        self.due = due
    }

    public func isDue(at date: Date) -> Bool { due <= date }
}

/// The FSRS parameters. One versioned blob, kept in NSUbiquitousKeyValueStore by the app; changing it
/// rebuilds every schedule (HANDOFF.md 5.2).
public struct FSRSParameters: Codable, Sendable, Hashable {
    public var version: Int
    public var weights: [Double]
    public var desiredRetention: Double
    public var maximumInterval: Int
    public var learningSteps: [TimeInterval]
    public var relearningSteps: [TimeInterval]
    /// Hour of the local day when the review day rolls over.
    public var dayStartHour: Int

    /// FSRS-6 default weights (21 parameters).
    public static let defaultWeights: [Double] = [
        0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666, 0.796,
        1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542,
    ]

    public static let `default` = FSRSParameters(
        version: 1, weights: defaultWeights, desiredRetention: 0.9, maximumInterval: 36500,
        learningSteps: [60, 600], relearningSteps: [600], dayStartHour: 4)

    public init(version: Int, weights: [Double], desiredRetention: Double, maximumInterval: Int,
                learningSteps: [TimeInterval], relearningSteps: [TimeInterval], dayStartHour: Int) {
        self.version = version
        self.weights = weights.count == 21 ? weights : Self.defaultWeights
        self.desiredRetention = desiredRetention
        self.maximumInterval = maximumInterval
        self.learningSteps = learningSteps
        self.relearningSteps = relearningSteps
        self.dayStartHour = dayStartHour
    }
}

/// Anything that turns review logs into a schedule. Replay must be deterministic (no fuzz).
public protocol Scheduler: Sendable {
    func review(_ schedule: Schedule, _ event: ReviewEvent) -> Schedule
}

extension Scheduler {
    /// Rebuild a schedule from an item's logs, in time order (ties broken by log UUID).
    public func replay(_ events: [ReviewEvent]) -> Schedule {
        let ordered = events.sorted {
            $0.reviewedAt != $1.reviewedAt ? $0.reviewedAt < $1.reviewedAt : $0.id.uuidString < $1.id.uuidString
        }
        return ordered.reduce(Schedule()) { review($0, $1) }
    }

    /// What each rating would schedule next, for the review buttons.
    public func preview(_ schedule: Schedule, at date: Date, tzOffsetMinutes: Int) -> [Rating: Date] {
        var out: [Rating: Date] = [:]
        for rating in Rating.allCases {
            out[rating] = review(schedule, ReviewEvent(reviewedAt: date, tzOffsetMinutes: tzOffsetMinutes, rating: rating)).due
        }
        return out
    }
}

/// FSRS-6, following the reference scheduler (py-fsrs 6) without fuzz.
public struct FSRSScheduler: Scheduler {
    public let parameters: FSRSParameters
    private var w: [Double] { parameters.weights }

    public init(parameters: FSRSParameters = .default) {
        self.parameters = parameters
    }

    // MARK: Memory model

    var decay: Double { -w[20] }
    var factor: Double { pow(0.9, 1 / decay) - 1 }

    public func retrievability(elapsedDays: Double, stability: Double) -> Double {
        guard stability > 0 else { return 0 }
        return pow(1 + factor * max(0, elapsedDays) / stability, decay)
    }

    func clampD(_ d: Double) -> Double { min(max(d, 1), 10) }
    func clampS(_ s: Double) -> Double { max(s, 0.001) }

    func initialStability(_ g: Rating) -> Double { clampS(w[g.rawValue - 1]) }

    func initialDifficultyRaw(_ g: Rating) -> Double { w[4] - exp(w[5] * Double(g.rawValue - 1)) + 1 }
    func initialDifficulty(_ g: Rating) -> Double { clampD(initialDifficultyRaw(g)) }

    func nextDifficulty(_ d: Double, _ g: Rating) -> Double {
        let delta = -w[6] * Double(g.rawValue - 3)
        let damped = d + delta * (10 - d) / 9
        let reverted = w[7] * initialDifficultyRaw(.easy) + (1 - w[7]) * damped
        return clampD(reverted)
    }

    func shortTermStability(_ s: Double, _ g: Rating) -> Double {
        var inc = exp(w[17] * (Double(g.rawValue) - 3 + w[18])) * pow(s, -w[19])
        if g >= .good { inc = max(inc, 1) }
        return clampS(s * inc)
    }

    func recallStability(_ d: Double, _ s: Double, _ r: Double, _ g: Rating) -> Double {
        let hardPenalty = g == .hard ? w[15] : 1
        let easyBonus = g == .easy ? w[16] : 1
        let inc = exp(w[8]) * (11 - d) * pow(s, -w[9]) * (exp((1 - r) * w[10]) - 1) * hardPenalty * easyBonus
        return clampS(s * (1 + inc))
    }

    func forgetStability(_ d: Double, _ s: Double, _ r: Double) -> Double {
        let longTerm = w[11] * pow(d, -w[12]) * (pow(s + 1, w[13]) - 1) * exp((1 - r) * w[14])
        let shortTerm = s / exp(w[17] * w[18])
        return clampS(min(longTerm, shortTerm))
    }

    public func interval(for stability: Double) -> Int {
        let days = stability / factor * (pow(parameters.desiredRetention, 1 / decay) - 1)
        return min(max(Int(days.rounded()), 1), parameters.maximumInterval)
    }

    // MARK: Review days

    /// The review day a moment falls on, counting days from 1970 in the reviewer's local time,
    /// with the day starting at `dayStartHour`.
    public func dayNumber(_ date: Date, tzOffsetMinutes: Int) -> Int {
        let local = date.timeIntervalSince1970 + Double(tzOffsetMinutes * 60) - Double(parameters.dayStartHour * 3600)
        return Int((local / 86400).rounded(.down))
    }

    /// The moment a review day starts, in the given time zone offset.
    public func startOfDay(_ day: Int, tzOffsetMinutes: Int) -> Date {
        Date(timeIntervalSince1970: Double(day) * 86400 + Double(parameters.dayStartHour * 3600) - Double(tzOffsetMinutes * 60))
    }

    // MARK: Review

    public func review(_ schedule: Schedule, _ event: ReviewEvent) -> Schedule {
        var s = schedule
        let g = event.rating
        let now = event.reviewedAt
        let tz = event.tzOffsetMinutes
        let elapsedDays: Int = s.lastReviewedAt.map { last in
            max(0, dayNumber(now, tzOffsetMinutes: tz) - dayNumber(last, tzOffsetMinutes: s.lastTZOffsetMinutes))
        } ?? 0

        // Memory state
        if s.state == .new || s.reps == 0 {
            s.stability = initialStability(g)
            s.difficulty = initialDifficulty(g)
            s.state = .learning
            s.step = 0
        } else {
            let r = retrievability(elapsedDays: Double(elapsedDays), stability: s.stability)
            if elapsedDays < 1 {
                s.stability = shortTermStability(s.stability, g)
            } else if g == .again {
                s.stability = forgetStability(s.difficulty, s.stability, r)
            } else {
                s.stability = recallStability(s.difficulty, s.stability, r, g)
            }
            s.difficulty = nextDifficulty(s.difficulty, g)
        }

        // Next due
        func scheduleDays() {
            let days = interval(for: s.stability)
            s.scheduledDays = days
            s.state = .review
            s.step = 0
            s.due = startOfDay(dayNumber(now, tzOffsetMinutes: tz) + days, tzOffsetMinutes: tz)
        }
        func scheduleIn(_ seconds: TimeInterval) {
            s.scheduledDays = 0
            s.due = now.addingTimeInterval(seconds)
        }

        switch s.state {
        case .learning, .relearning:
            let steps = s.state == .learning ? parameters.learningSteps : parameters.relearningSteps
            if steps.isEmpty || (s.step >= steps.count && g >= .hard) {
                scheduleDays()
                break
            }
            switch g {
            case .again:
                s.step = 0
                scheduleIn(steps[0])
            case .hard:
                if s.step == 0 && steps.count == 1 {
                    scheduleIn(steps[0] * 1.5)
                } else if s.step == 0 {
                    scheduleIn((steps[0] + steps[1]) / 2)
                } else {
                    scheduleIn(steps[min(s.step, steps.count - 1)])
                }
            case .good:
                if s.step + 1 >= steps.count {
                    scheduleDays()
                } else {
                    s.step += 1
                    scheduleIn(steps[s.step])
                }
            case .easy:
                scheduleDays()
            }
        case .review:
            if g == .again {
                s.lapses += 1
                if parameters.relearningSteps.isEmpty {
                    scheduleDays()
                } else {
                    s.state = .relearning
                    s.step = 0
                    scheduleIn(parameters.relearningSteps[0])
                }
            } else {
                scheduleDays()
            }
        case .new:
            scheduleDays()
        }

        s.reps += 1
        s.lastReviewedAt = now
        s.lastTZOffsetMinutes = tz
        return s
    }
}
