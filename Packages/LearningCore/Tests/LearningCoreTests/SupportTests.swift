import Foundation
import Testing

@testable import LearningCore

@Suite struct SupportTests {
    @Test func fnv1a64KnownVectors() {
        // Published FNV-1a 64 test vectors.
        #expect(FNV1a64.hash("") == 0xcbf2_9ce4_8422_2325)
        #expect(FNV1a64.hash("a") == 0xaf63_dc4c_8601_ec8c)
        #expect(FNV1a64.hash("foobar") == 0x8594_4171_f739_67e8)
    }

    @Test func splitMix64KnownVector() {
        // Reference values for seed 0 from the SplitMix64 reference implementation.
        var rng = SplitMix64(seed: 0)
        #expect(rng.next() == 0xe220_a839_7b1d_cdaf)
        #expect(rng.next() == 0x6e78_9e6a_a1b9_65f4)
    }

    @Test func seededShuffleIsStableAndAPermutation() {
        let ids = (1...10).map { "u02.l1.ex\($0)" }
        let a = ids.seededShuffle(seed: "u02.l1.step-practice")
        let b = ids.seededShuffle(seed: "u02.l1.step-practice")
        #expect(a == b)
        #expect(a.sorted() == ids.sorted())
        #expect(a != ids)
    }

    @Test func localDayRollsOverAtFourAM() {
        // 2026-01-05T03:59:59Z in UTC is still 2026-01-04; 04:00 starts the 5th.
        let before = Int64(1_767_585_599_000)
        #expect(LocalDay.string(ms: before, tzOffsetMinutes: 0) == "2026-01-04")
        #expect(LocalDay.string(ms: before + 1_000, tzOffsetMinutes: 0) == "2026-01-05")
        // In UTC+2, 02:00Z is 04:00 local.
        #expect(LocalDay.string(ms: before + 1_000 - 2 * 3_600_000, tzOffsetMinutes: 120) == "2026-01-05")
        let day = LocalDay.dayNumber(ms: before + 1_000, tzOffsetMinutes: 0)
        #expect(LocalDay.isoWeekday(dayNumber: day) == 1)  // 2026-01-05 is a Monday
        #expect(LocalDay.endMs(dayNumber: day, tzOffsetMinutes: 0) == before + 1_000 + 86_400_000)
    }

    @Test func seededUUIDsAreLowercaseV4AndDeterministic() {
        let a = SeededUUIDSource(seed: "x")
        let b = SeededUUIDSource(seed: "x")
        let id = a.next()
        #expect(id == b.next())
        #expect(id == id.lowercased())
        #expect(UUID(uuidString: id) != nil)
        #expect(Array(id)[14] == "4")
    }
}
