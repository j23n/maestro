// swift-tools-version: 6.2
// LearningCore: pure Swift, Foundation only, Linux-tested (docs/02, ADR-02; CLAUDE.md hard rule 3).
import PackageDescription

let package = Package(
    name: "LearningCore",
    platforms: [.iOS(.v26), .macOS(.v26)],
    products: [
        .library(name: "LearningCore", targets: ["LearningCore"])
    ],
    targets: [
        .target(
            name: "LearningCore",
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
        .testTarget(
            name: "LearningCoreTests",
            dependencies: ["LearningCore"],
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
    ]
)
