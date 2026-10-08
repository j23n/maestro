import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// M3.9: the launch errors of docs/02 § Logging and errors, end to end through `AppModel.start()`: a pack of another
/// schema version gives the blocking pack-mismatch screen and leaves the learner's progress alone; a learner
/// database that can't be opened is moved aside, a fresh one opens, the learner is told in one sentence, and the
/// progress sync brings back is picked up.
@MainActor
@Suite struct LaunchErrorTests {
    let shell = ShellTestApp()

    /// A copy of the mini pack whose `meta.schema_version` is `version`. The pack is opened read-only by the app,
    /// so the test edits the copy's bytes: the meta row's record holds the key and the value side by side, and the
    /// one-digit value keeps its length, so the page stays valid SQLite.
    func packWithSchemaVersion(_ version: Character) throws -> URL {
        var bytes = [UInt8](try Data(contentsOf: PackAdaptersTests.packURL))
        let needle = Array("schema_version\(PackReader.schemaVersion)".utf8)
        let hits = (0...(bytes.count - needle.count)).filter { bytes[$0..<($0 + needle.count)].elementsEqual(needle) }
        try #require(hits.count == 1, "the mini pack's meta row should appear once, found \(hits.count)")
        bytes[hits[0] + needle.count - 1] = try #require(version.asciiValue)
        try FileManager.default.createDirectory(at: shell.folder, withIntermediateDirectories: true)
        let url = shell.folder.appendingPathComponent("content-v\(version).sqlite")
        try Data(bytes).write(to: url)
        return url
    }

    func app(pack: URL, learner: URL, seed: String = "a") -> AppModel {
        AppModel(
            env: .init(
                packURL: pack, learnerURL: learner, clock: shell.base, ids: SeededUUIDSource(seed: seed),
                platform: .iPhone))
    }

    var learnerURL: URL { shell.folder.appendingPathComponent("learner.sqlite") }

    @Test func aPackOfAnotherSchemaVersionShowsThePackMismatchScreen() async throws {
        // Some progress first, on the right pack.
        let before = await shell.started()
        try await before.debugJumpAtLaunch(to: "u02")
        try before.store?.close()
        let progress = try Data(contentsOf: learnerURL)

        let app = app(pack: try packWithSchemaVersion("9"), learner: learnerURL, seed: "b")
        await app.start()
        guard case .packMismatch(let detail) = app.phase else {
            Issue.record("expected the pack-mismatch screen, got \(app.phase)")
            return
        }
        #expect(detail.contains("schema version 9") && detail.contains("reads \(PackReader.schemaVersion)"))
        // Nothing else opened: no learner store, no Today, and the learner's database untouched ("your progress is
        // safe"), with no backup made of it.
        #expect(app.store == nil && app.today == nil && app.recoveryNotice == nil)
        #expect(try Data(contentsOf: learnerURL) == progress)
        let files = try FileManager.default.contentsOfDirectory(atPath: shell.folder.path)
        #expect(!files.contains { $0.contains(".corrupt.") })
    }

    @Test func thePackOfThisVersionStillOpensFromACopy() async throws {
        // The byte edit itself is sound: the same digit gives a working pack.
        let app = app(pack: try packWithSchemaVersion(Character("\(PackReader.schemaVersion)")), learner: learnerURL)
        await app.start()
        #expect(app.phase == .ready)
    }

    @Test func aFileThatIsNotADatabaseIsMovedAsideAndAFreshOneOpens() async throws {
        try FileManager.default.createDirectory(at: shell.folder, withIntermediateDirectories: true)
        let garbage = Data(String(repeating: "not a database ", count: 400).utf8)
        try garbage.write(to: learnerURL)
        let app = app(pack: PackAdaptersTests.packURL, learner: learnerURL)
        await app.start()
        #expect(app.phase == .ready)
        let notice = try #require(app.recoveryNotice)
        #expect(notice.hasSuffix(".") && notice.split(separator: ".").count == 1)  // one sentence
        let backup = shell.folder.appendingPathComponent("learner-2026-10-06-073000.corrupt.sqlite")
        #expect(try Data(contentsOf: backup) == garbage)
        // A fresh database: first launch again, and it takes writes.
        #expect(!app.isOnboarded && app.state?.introductions.isEmpty == true)
        try await app.debugJumpAtLaunch(to: "u02")
        #expect(try await shell.events(app).map(\.type) == ["onboardingCompleted", "placementCompleted", "introduced"])
    }

    @Test func aDamagedDatabaseIsRecoveredOnceAndSyncedSettingsEndOnboarding() async throws {
        let first = await shell.started()
        try await first.debugJumpAtLaunch(to: "u02")
        #expect(first.isOnboarded)
        try first.store?.close()
        // Damage the schema page (everything after the 100-byte header of page 1), as a failing disk might, and the
        // write-ahead log's header with it: SQLite ignores a log whose header is invalid, so it reads the damaged page.
        let damage: [(path: String, offset: UInt64, count: Int)] = [
            (learnerURL.path, 100, 3_996), (learnerURL.path + "-wal", 0, 32),
        ]
        for d in damage where FileManager.default.fileExists(atPath: d.path) {
            let handle = try #require(FileHandle(forUpdatingAtPath: d.path))
            try handle.seek(toOffset: d.offset)
            try handle.write(contentsOf: Data(repeating: 0xA5, count: d.count))
            try handle.close()
        }

        let recovered = app(pack: PackAdaptersTests.packURL, learner: learnerURL, seed: "b")
        await recovered.start()
        #expect(recovered.phase == .ready && recovered.recoveryNotice != nil, "\(recovered.phase)")
        let eventsAfterRecovery = try await shell.events(recovered)
        #expect(!recovered.isOnboarded && eventsAfterRecovery.isEmpty)

        // Sync brings the learner's synced settings back (docs/02: "let sync download the events again"): the
        // profile written on another device ends onboarding here too, without asking again.
        let store = try #require(recovered.store)
        let forms = SettingRecord(
            .profileForms, value: .string("f"), updatedAt: shell.base.nowMs(), deviceId: "other-device")
        _ = try await store.applyRemote(forms)
        for _ in 0..<200 where !recovered.isOnboarded { try await Task.sleep(for: .milliseconds(5)) }
        #expect(recovered.isOnboarded && recovered.settings.profileForms == .f)

        // The next launch opens the recovered database normally: no second notice, one backup.
        try store.close()
        let again = app(pack: PackAdaptersTests.packURL, learner: learnerURL, seed: "c")
        await again.start()
        #expect(again.phase == .ready && again.recoveryNotice == nil && again.isOnboarded)
        let backups = try FileManager.default.contentsOfDirectory(atPath: shell.folder.path)
            .filter { $0.hasSuffix(".corrupt.sqlite") }
        #expect(backups.count == 1)
    }
}
