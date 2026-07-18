// swift-tools-version:6.0
// ⚠️ UNTESTED SCAFFOLD — requires macOS 26 + Apple silicon + Xcode 26.
// Build: swift build -c release   (from this directory, on the Mac)
import PackageDescription

let package = Package(
    name: "applefm-runner",
    platforms: [.macOS("26.0")],
    targets: [
        .executableTarget(name: "applefm-runner", path: "Sources")
    ]
)
