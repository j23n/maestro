import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// The in-memory two-device simulation of task M7.2's proxy (docs/08 § Tests): an iPhone and an iPad on one iCloud
/// account learn, change settings (the same keys on both), go offline, sync partly, crash and relaunch, and pause,
/// in a seeded random order, with skewed clocks and random batch sizes. Once both are back online and have synced,
/// they hold the same events as the server, byte-identical derived state (equal to a full rebuild), the same synced
/// settings (the last writer's), their own device settings, and nothing pending.
@Suite struct SyncSimulationTests {
    static let start: Int64 = 1_767_603_600_000
    static let sharedKeys: [SettingKey] = [.goalDaysPerWeek, .reviewDailyLimit, .answersStrictForms, .profileName]

    @Test(arguments: 0..<16)
    func twoDevicesConverge(seed: Int) async throws {
        var rng = SplitMix64(seedString: "sync-simulation-\(seed)")
        let shared = FakeCloud()
        func device(_ name: String, _ platform: Platform, skew: Int64) throws -> SyncTestDevice {
            try SyncTestDevice(
                "\(name)-\(seed)", platform: platform, account: .init(user: "_learner", cloud: shared),
                start: Self.start + skew, fetchBatch: 1 + rng.nextInt(below: 4), sendBatch: 1 + rng.nextInt(below: 5),
                insertBatchLimit: 1 + rng.nextInt(below: 8))
        }
        let phone = try device("phone", .iPhone, skew: 0)
        let pad = try device("pad", .iPad, skew: Int64(rng.nextInt(below: 600_000)) - 300_000)
        let devices = [phone, pad]
        var textScale: [ObjectIdentifier: Double] = [:]
        var paused: Set<ObjectIdentifier> = []
        for device in devices { await device.driver.start() }

        for _ in 0..<45 {
            let device = devices[rng.nextInt(below: devices.count)]
            let id = ObjectIdentifier(device)
            switch rng.nextInt(below: 100) {
            case 0..<24:
                let outcomes: [AttemptOutcome] = [.correct, .correct, .almost, .wrong, .revealed, .skipped]
                try await device.lesson(
                    outcomes: (0..<(1 + rng.nextInt(below: 5))).map { _ in
                        outcomes[rng.nextInt(below: outcomes.count)]
                    })
            case 24..<32:
                try await device.gloss()
            case 32..<46:
                let key = Self.sharedKeys[rng.nextInt(below: Self.sharedKeys.count)]
                try await device.set(key, Self.value(for: key, &rng))
            case 46..<50:
                let scale = [0.9, 1.0, 1.2, 1.4][rng.nextInt(below: 4)]
                try await device.set(.displayTextScale, .number(scale))
                textScale[id] = scale
            case 50..<70:
                try await device.sync()
            case 70..<76:
                if let engine = device.engine { try? await engine.fetchChanges() }  // a fetch with no send
            case 76..<82:
                device.icloud.networkUp.toggle()
            case 82..<87:
                try device.relaunch()
                await device.driver.start()
            case 87..<91:
                let pause = !paused.contains(id)
                await device.driver.setPaused(pause)
                if pause { paused.insert(id) } else { paused.remove(id) }
            default:
                device.clock.advance(byMs: Int64(rng.nextInt(below: 36 * 3_600_000)))
            }
        }

        for device in devices {
            device.icloud.networkUp = true
            if paused.contains(ObjectIdentifier(device)) { await device.driver.setPaused(false) }
        }
        for _ in 0..<4 {
            for device in devices { try await device.sync() }
        }

        let phoneEvents = try await phone.store.events()
        let padEvents = try await pad.store.events()
        #expect(phoneEvents.map(\.id) == padEvents.map(\.id))
        #expect(shared.eventIDs == Set(phoneEvents.map(\.id)))
        #expect(phone.store.state == pad.store.state)
        let incremental = phone.store.state
        #expect(try await phone.store.rebuildAll() == incremental)
        for key in SettingKey.allCases where key.scope == .synced {
            let a = phone.store.settings.records[key.rawValue]
            let b = pad.store.settings.records[key.rawValue]
            #expect(a == b, "\(key.rawValue)")
            #expect(shared.setting(key) == a, "\(key.rawValue) on the server")
        }
        for device in devices {
            #expect(device.store.settings.textScale == textScale[ObjectIdentifier(device)] ?? 1.0)
            #expect(try await device.pendingNames.isEmpty)
            #expect(device.engine?.pendingSaves.isEmpty == true)
            #expect(await device.snapshot()?.status == .synced(atMs: device.clock.nowMs()))
        }
    }

    static func value(for key: SettingKey, _ rng: inout SplitMix64) -> JSONValue {
        switch key {
        case .goalDaysPerWeek: .number(Double(1 + rng.nextInt(below: 7)))
        case .reviewDailyLimit: .number(Double(20 + 10 * rng.nextInt(below: 9)))
        case .answersStrictForms: .bool(rng.nextInt(below: 2) == 0)
        default: .string("Learner \(rng.nextInt(below: 100))")
        }
    }
}
