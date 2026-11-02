// swift-tools-version: 6.2
// MaestroKit: the app's logic, kept free of Apple-only frameworks so Linux CI builds and tests it.
// SwiftData models, speech and the UI live in the app target.
import PackageDescription

let package = Package(
    name: "MaestroKit",
    platforms: [.iOS(.v26), .macOS(.v26)],
    products: [
        .library(name: "LanguageCore", targets: ["LanguageCore"]),
        .library(name: "LexiconKit", targets: ["LexiconKit"]),
        .library(name: "GrammarKit", targets: ["GrammarKit"]),
        .library(name: "PackKit", targets: ["PackKit"]),
        .library(name: "SRSKit", targets: ["SRSKit"]),
        .library(name: "SyncLogic", targets: ["SyncLogic"]),
        .library(name: "PracticeKit", targets: ["PracticeKit"]),
    ],
    targets: [
        // The SDK's SQLite on Apple platforms, libsqlite3-dev on Linux. No pkg-config: on a Mac it
        // finds Homebrew's macOS-only library and breaks the iOS build.
        .systemLibrary(name: "CSQLite", path: "Sources/CSQLite"),
        .target(name: "LanguageCore"),
        .target(name: "LexiconKit", dependencies: ["LanguageCore", "CSQLite"]),
        .target(name: "GrammarKit", dependencies: ["LanguageCore", "LexiconKit"]),
        .target(name: "PackKit", dependencies: ["LanguageCore"]),
        .target(name: "SRSKit"),
        .target(name: "SyncLogic", dependencies: ["LanguageCore"]),
        .target(name: "PracticeKit", dependencies: ["LanguageCore", "PackKit"]),
        .testTarget(name: "LanguageCoreTests", dependencies: ["LanguageCore"]),
        .testTarget(name: "LexiconKitTests", dependencies: ["LexiconKit"], resources: [.copy("Fixtures")]),
        .testTarget(name: "GrammarKitTests", dependencies: ["GrammarKit", "LexiconKit"], resources: [.copy("Fixtures")]),
        .testTarget(name: "PackKitTests", dependencies: ["PackKit"], resources: [.copy("Fixtures")]),
        .testTarget(name: "SRSKitTests", dependencies: ["SRSKit"]),
        .testTarget(name: "SyncLogicTests", dependencies: ["SyncLogic", "LanguageCore"]),
        .testTarget(name: "PracticeKitTests", dependencies: ["PracticeKit", "PackKit"]),
    ],
    swiftLanguageModes: [.v6]
)
