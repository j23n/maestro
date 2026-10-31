// swift-tools-version: 6.2
// MaestroKit: the app's logic, kept free of Apple-only frameworks so Linux CI builds and tests it.
// SwiftData models, speech and the UI live in the app target.
import PackageDescription

let package = Package(
    name: "MaestroKit",
    platforms: [.iOS(.v26), .macOS(.v26)],
    products: [
        .library(name: "ItalianCore", targets: ["ItalianCore"]),
        .library(name: "LexiconKit", targets: ["LexiconKit"]),
        .library(name: "GrammarKit", targets: ["GrammarKit"]),
        .library(name: "PackKit", targets: ["PackKit"]),
        .library(name: "SRSKit", targets: ["SRSKit"]),
        .library(name: "SyncLogic", targets: ["SyncLogic"]),
    ],
    targets: [
        // The SDK's SQLite on Apple platforms, libsqlite3-dev on Linux. No pkg-config: on a Mac it
        // finds Homebrew's macOS-only library and breaks the iOS build.
        .systemLibrary(name: "CSQLite", path: "Sources/CSQLite"),
        .target(name: "ItalianCore"),
        .target(name: "LexiconKit", dependencies: ["ItalianCore", "CSQLite"]),
        .target(name: "GrammarKit", dependencies: ["ItalianCore", "LexiconKit"]),
        .target(name: "PackKit", dependencies: ["ItalianCore"]),
        .target(name: "SRSKit"),
        .target(name: "SyncLogic", dependencies: ["ItalianCore"]),
        .testTarget(name: "ItalianCoreTests", dependencies: ["ItalianCore"]),
        .testTarget(name: "LexiconKitTests", dependencies: ["LexiconKit"], resources: [.copy("Fixtures")]),
        .testTarget(name: "GrammarKitTests", dependencies: ["GrammarKit", "LexiconKit"], resources: [.copy("Fixtures")]),
        .testTarget(name: "PackKitTests", dependencies: ["PackKit"], resources: [.copy("Fixtures")]),
        .testTarget(name: "SRSKitTests", dependencies: ["SRSKit"]),
        .testTarget(name: "SyncLogicTests", dependencies: ["SyncLogic", "ItalianCore"]),
    ],
    swiftLanguageModes: [.v6]
)
