// swift-tools-version: 6.2
// LearningCore: pure Swift, Foundation only, Linux-tested (docs/02, ADR-02; CLAUDE.md hard rule 3).
import PackageDescription

let package = Package(
    name: "LearningCore",
    platforms: [.iOS(.v26), .macOS(.v26)],
    products: [
        .library(name: "LearningCore", targets: ["LearningCore"]),
        // The synthetic course of the engine tests, shared with the Storage tests (fixtures/replay). Never linked
        // into the app.
        .library(name: "LearningCoreTestSupport", targets: ["LearningCoreTestSupport"]),
    ],
    targets: [
        .target(
            name: "LearningCore",
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
        .target(
            name: "LearningCoreTestSupport",
            dependencies: ["LearningCore"],
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
        .testTarget(
            name: "LearningCoreTests",
            dependencies: ["LearningCore", "LearningCoreTestSupport"],
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
    ]
)
