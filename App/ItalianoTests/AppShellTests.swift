import Foundation
import LearningCore
import Testing

@testable import Italiano

/// M3.8: the View menu's text-size commands and Settings → Acknowledgements.
@MainActor
@Suite struct AppShellTests {
    let shell = ShellTestApp()

    @Test func textSizeCommandsStepThroughTheRange() {
        #expect(TextSizeCommand.bigger.apply(to: 1.0) == 1.1)
        #expect(TextSizeCommand.bigger.apply(to: 1.05) == 1.1)  // between steps (the Settings slider)
        #expect(TextSizeCommand.smaller.apply(to: 1.0) == 0.9)
        #expect(TextSizeCommand.smaller.apply(to: 0.9) == 0.85)
        #expect(TextSizeCommand.smaller.apply(to: 0.85) == 0.85)
        #expect(TextSizeCommand.bigger.apply(to: 1.6) == 1.6)
        #expect(TextSizeCommand.actualSize.apply(to: 1.3) == 1.0)
        #expect(!TextSizeCommand.bigger.canApply(to: 1.6) && !TextSizeCommand.smaller.canApply(to: 0.85))
        #expect(!TextSizeCommand.actualSize.canApply(to: 1.0) && TextSizeCommand.actualSize.canApply(to: 0.9))
        // Every step is inside the setting's range.
        #expect(TextSizeCommand.steps.allSatisfy { LearnerSettings.textScaleRange.contains($0) })
        #expect(TextSizeCommand.steps.first == LearnerSettings.textScaleRange.lowerBound)
        #expect(TextSizeCommand.steps.last == LearnerSettings.textScaleRange.upperBound)
    }

    @Test func textSizeCommandsChangeTheDeviceSetting() async throws {
        let app = await shell.started()
        let textSize = TextSizeController(app: app)
        // Two quick presses: the second steps from what the first wrote.
        textSize.apply(.bigger)
        textSize.apply(.bigger)
        #expect(textSize.current == 1.2)
        await textSize.settle()
        #expect(app.settings.textScale == 1.2 && textSize.current == 1.2)
        textSize.apply(.actualSize)
        await textSize.settle()
        #expect(app.settings.textScale == 1.0 && !textSize.canApply(.actualSize))
        // The Settings slider moves it elsewhere; the commands start from there.
        app.set(.displayTextScale, to: .number(1.45))
        await app.settle()
        textSize.apply(.smaller)
        await textSize.settle()
        #expect(app.settings.textScale == 1.4)
        let record = try #require(try await app.store?.settingRecord(SettingKey.displayTextScale.rawValue))
        #expect(record.scope == .device)  // never synced (docs/08)
    }

    // MARK: Acknowledgements

    static let licenses = PayloadFixtures.repoRoot.appendingPathComponent("App/Italiano/Resources/Licenses")

    @Test func everyLicenceTextIsThere() throws {
        for entry in Acknowledgements.all where entry.licenceFile != nil || entry.licenceText != nil {
            let text = try #require(Acknowledgements.licenceText(for: entry, in: [Self.licenses]), "\(entry.id)")
            #expect(!text.isEmpty)
        }
        let fonts = Acknowledgements.all.filter { $0.licence.hasPrefix("SIL Open Font License") }
        #expect(fonts.map(\.name) == ["Literata", "Instrument Sans"])
        for font in fonts {
            let text = try #require(Acknowledgements.licenceText(for: font, in: [Self.licenses]))
            #expect(text.contains("SIL OPEN FONT LICENSE Version 1.1"))
            #expect(text.hasPrefix("Copyright"))
        }
        // The fonts the app bundles are the ones credited.
        let bundled = try FileManager.default.contentsOfDirectory(
            atPath: PayloadFixtures.repoRoot.appendingPathComponent("App/Italiano/Resources/Fonts").path)
        for name in ["Literata", "InstrumentSans"] { #expect(bundled.contains { $0.hasPrefix(name) }) }
        // A missing folder finds nothing (rather than crashing the screen).
        let literata = try #require(Acknowledgements.all.first { $0.id == "literata" })
        #expect(Acknowledgements.licenceText(for: literata, in: [URL(fileURLWithPath: "/nonexistent")]) == nil)
        #expect(Acknowledgements.all.first { $0.id == "voices" }?.credit.contains("synthetic voices") == true)
    }

    /// GRDB's LICENSE in the checkout this build resolved: `scripts/check-app-logic.sh` passes its SwiftPM build
    /// folder (`ITALIANO_SWIFTPM_BUILD`); `swift build` in Packages/Storage leaves one there; Xcode keeps package
    /// checkouts in `SourcePackages` next to the build products.
    nonisolated static let grdbLicence: URL? = {
        let env = ProcessInfo.processInfo.environment
        var candidates = [
            env["ITALIANO_SWIFTPM_BUILD"].map { URL(fileURLWithPath: $0).appendingPathComponent("checkouts") },
            PayloadFixtures.repoRoot.appendingPathComponent("Packages/Storage/.build/checkouts"),
        ].compactMap { $0 }
        var folder = Bundle.main.bundleURL
        while folder.pathComponents.count > 1 {
            folder.deleteLastPathComponent()
            candidates.append(folder.appendingPathComponent("SourcePackages/checkouts"))
        }
        return candidates.map { $0.appendingPathComponent("GRDB.swift/LICENSE") }
            .first { FileManager.default.fileExists(atPath: $0.path) }
    }()

    /// Under `scripts/check-app-logic.sh` (which sets ITALIANO_ROOT) the checkout always exists, so the test runs and
    /// requires it; elsewhere it is reported as skipped when no checkout can be found.
    @Test(
        .enabled(
            if: grdbLicence != nil || ProcessInfo.processInfo.environment["ITALIANO_ROOT"] != nil,
            "no GRDB.swift checkout found to compare the notice with"))
    func theGRDBNoticeMatchesItsLicence() throws {
        let url = try #require(Self.grdbLicence, "GRDB.swift/LICENSE is missing from the SwiftPM checkouts")
        let original = try String(contentsOf: url, encoding: .utf8)
        func words(_ s: String) -> [Substring] { s.split(whereSeparator: \.isWhitespace) }
        #expect(words(Acknowledgements.mitGRDB) == words(original))
    }

    /// "Acknowledgements complete": every row of docs/13 § Licences is credited or deliberately left out.
    @Test func everyLicenceRowOfDocs13IsAccountedFor() throws {
        let doc = try String(
            contentsOf: PayloadFixtures.repoRoot.appendingPathComponent("docs/13-decisions.md"), encoding: .utf8)
        let section = try #require(doc.components(separatedBy: "## Licences").dropFirst().first)
            .components(separatedBy: "\n## ")[0]
        let rows = section.split(separator: "\n").filter { $0.hasPrefix("| ") && !$0.hasPrefix("| Resource") }
            .map { $0.dropFirst(2).components(separatedBy: " |")[0] }
        #expect(rows.count >= 9)
        let covered = Acknowledgements.all.map(\.docsRow) + Array(Acknowledgements.notCredited.keys)
        for row in rows {
            #expect(covered.contains { row.hasPrefix($0) }, "docs/13 row not acknowledged: \(row)")
        }
        #expect(Set(Acknowledgements.all.map(\.id)).count == Acknowledgements.all.count)
    }
}
