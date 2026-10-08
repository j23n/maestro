// swift-tools-version: 6.2
// Storage: GRDB-backed content pack reader and learner database (docs/02, ADR-03).
import PackageDescription

let package = Package(
    name: "Storage",
    platforms: [.iOS(.v26), .macOS(.v26)],
    products: [
        .library(name: "Storage", targets: ["Storage"])
    ],
    dependencies: [
        .package(path: "../LearningCore"),
        .package(url: "https://github.com/groue/GRDB.swift.git", exact: "7.11.1"),
    ],
    targets: [
        .target(
            name: "Storage",
            dependencies: [
                "LearningCore",
                .product(name: "GRDB", package: "GRDB.swift"),
            ],
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
        .testTarget(
            name: "StorageTests",
            dependencies: [
                "Storage", "LearningCore",
                .product(name: "LearningCoreTestSupport", package: "LearningCore"),
            ],
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
    ]
)
