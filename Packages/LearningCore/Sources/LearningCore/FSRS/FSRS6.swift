import Foundation

/// Memory state of one (item, skill) pair (docs/03 `memory` table). Times are UTC milliseconds.
public struct MemoryState: Codable, Hashable, Sendable {
    public var stability: Double
    public var difficulty: Double
    public var lastReviewMs: Int64
    public var dueMs: Int64
    /// Number of reviews (FSRS updates) so far.
    public var reps: Int
    /// Again ratings after the first review.
    public var lapses: Int

    public init(stability: Double, difficulty: Double, lastReviewMs: Int64, dueMs: Int64, reps: Int, lapses: Int) {
        self.stability = stability
        self.difficulty = difficulty
        self.lastReviewMs = lastReviewMs
        self.dueMs = dueMs
        self.reps = reps
        self.lapses = lapses
    }
}

/// FSRS-6 exactly as `docs/05` § FSRS-6 and py-fsrs 6.3.2 with our config (ADR-05): default parameters,
/// desired retention 0.9, no learning or relearning steps, no fuzz, maximum interval 36,500 days.
/// Verified against `fixtures/fsrs/fsrs6-reference.json` (relative tolerance 1e-9, exact due dates).
public struct FSRS6: Sendable {
    public static let defaultParameters: [Double] = [
        0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666, 0.796,
        1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542,
    ]
    public static let minStability = 0.001
    public static let secondsPerDay: Int64 = 86_400
    public static let msPerDay: Int64 = 86_400_000

    public let w: [Double]
    public let desiredRetention: Double
    public let maximumIntervalDays: Int64
    public let decay: Double
    public let factor: Double

    public init(parameters: [Double] = FSRS6.defaultParameters, desiredRetention: Double = 0.9,
                maximumIntervalDays: Int64 = 36_500)
    {
        precondition(parameters.count == 21, "FSRS-6 needs 21 parameters")
        w = parameters
        self.desiredRetention = desiredRetention
        self.maximumIntervalDays = maximumIntervalDays
        decay = -parameters[20]
        factor = pow(0.9, 1 / decay) - 1
    }

    /// Whole days elapsed: floor(seconds / 86400), like Python's `timedelta.days` (never calendar days).
    public static func elapsedDays(fromMs: Int64, toMs: Int64) -> Int64 {
        let seconds = LocalDay.floorDiv(toMs - fromMs, 1000)
        return LocalDay.floorDiv(seconds, secondsPerDay)
    }

    /// R(t, S) = (1 + FACTOR · t / S)^DECAY with t in whole days (negative t counts as 0).
    public func retrievability(elapsedDays t: Int64, stability s: Double) -> Double {
        pow(1 + factor * Double(max(t, 0)) / s, decay)
    }

    /// Current retrievability of a state at `atMs`.
    public func retrievability(_ state: MemoryState, atMs: Int64) -> Double {
        retrievability(elapsedDays: Self.elapsedDays(fromMs: state.lastReviewMs, toMs: atMs), stability: state.stability)
    }

    public func initialStability(_ g: FSRSRating) -> Double {
        max(w[g.rawValue - 1], Self.minStability)
    }

    public func initialDifficulty(_ g: FSRSRating, clamp: Bool = true) -> Double {
        let d = w[4] - exp(w[5] * Double(g.rawValue - 1)) + 1
        return clamp ? min(max(d, 1), 10) : d
    }

    func shortTermStability(_ s: Double, _ g: FSRSRating) -> Double {
        var inc = exp(w[17] * (Double(g.rawValue) - 3 + w[18])) * pow(s, -w[19])
        // docs/05: for G ≥ 2 the same-day increase is at least 1 (a same-day Hard keeps stability; fixtures agree).
        if g.rawValue >= 2 { inc = max(inc, 1) }
        return max(s * inc, Self.minStability)
    }

    func forgetStability(d: Double, s: Double, r: Double) -> Double {
        let longTerm = w[11] * pow(d, -w[12]) * (pow(s + 1, w[13]) - 1) * exp((1 - r) * w[14])
        let shortTerm = s / exp(w[17] * w[18])
        return max(min(longTerm, shortTerm), Self.minStability)
    }

    func recallStability(d: Double, s: Double, r: Double, _ g: FSRSRating) -> Double {
        let hard = g == .hard ? w[15] : 1
        let easy = g == .easy ? w[16] : 1
        let next = s * (1 + exp(w[8]) * (11 - d) * pow(s, -w[9]) * (exp((1 - r) * w[10]) - 1) * hard * easy)
        return max(next, Self.minStability)
    }

    func nextDifficulty(_ d: Double, _ g: FSRSRating) -> Double {
        let delta = -w[6] * (Double(g.rawValue) - 3)
        let damped = d + delta * (10 - d) / 9
        let reverted = w[7] * initialDifficulty(.easy, clamp: false) + (1 - w[7]) * damped
        return min(max(reverted, 1), 10)
    }

    /// I = (S / FACTOR) · (r^(1/DECAY) − 1), before rounding.
    public func rawInterval(stability s: Double) -> Double {
        (s / factor) * (pow(desiredRetention, 1 / decay) - 1)
    }

    /// Round half to even (Python's `round`), then clamp to [1, maximum] days.
    public func intervalDays(stability s: Double) -> Int64 {
        let rounded = Self.roundHalfEven(rawInterval(stability: s))
        return min(max(Int64(rounded), 1), maximumIntervalDays)
    }

    public static func roundHalfEven(_ x: Double) -> Double {
        x.rounded(.toNearestOrEven)
    }

    /// One review at `atMs` with rating `g`. `state == nil` is a new card's first review.
    public func review(_ state: MemoryState?, rating g: FSRSRating, atMs: Int64) -> MemoryState {
        let s: Double
        let d: Double
        var reps = 1
        var lapses = 0
        if let prev = state {
            let t = Self.elapsedDays(fromMs: prev.lastReviewMs, toMs: atMs)
            if t < 1 {
                s = shortTermStability(prev.stability, g)
            } else {
                let r = retrievability(elapsedDays: t, stability: prev.stability)
                s = g == .again
                    ? forgetStability(d: prev.difficulty, s: prev.stability, r: r)
                    : recallStability(d: prev.difficulty, s: prev.stability, r: r, g)
            }
            d = nextDifficulty(prev.difficulty, g)
            reps = prev.reps + 1
            lapses = prev.lapses + (g == .again ? 1 : 0)
        } else {
            s = initialStability(g)
            d = initialDifficulty(g)
        }
        let due = atMs + intervalDays(stability: s) * Self.msPerDay
        return MemoryState(stability: s, difficulty: d, lastReviewMs: atMs, dueMs: due, reps: reps, lapses: lapses)
    }
}
