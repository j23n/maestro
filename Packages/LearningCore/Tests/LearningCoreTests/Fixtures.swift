import Foundation

/// Repo-root fixtures, found from this file's path (SwiftPM can't bundle files outside a package; docs/10).
enum Fixtures {
    static let repoRoot: URL = {
        var url = URL(fileURLWithPath: #filePath)
        // …/Packages/LearningCore/Tests/LearningCoreTests/Fixtures.swift → repo root is five levels up.
        for _ in 0..<5 { url.deleteLastPathComponent() }
        return url
    }()

    static func url(_ relative: String) -> URL { repoRoot.appendingPathComponent(relative) }

    static func data(_ relative: String) throws -> Data { try Data(contentsOf: url(relative)) }

    static func json(_ relative: String) throws -> Any {
        try JSONSerialization.jsonObject(with: data(relative))
    }

    /// `2026-01-05T09:00:00Z` → milliseconds since the epoch.
    static func ms(_ iso: String) -> Int64 {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        guard let date = f.date(from: iso) else { fatalError("bad ISO date \(iso)") }
        return Int64((date.timeIntervalSince1970 * 1000).rounded())
    }
}
