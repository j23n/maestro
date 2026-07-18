// ⚠️ UNTESTED SCAFFOLD.
//
// Pack updates: fetch release.json from the configured static host,
// compare versions, download the bundle, verify sha256, swap atomically.
// This is the ONLY network access in the core loop, and it's
// content-download only.

import CryptoKit
import Foundation

struct ReleaseInfo: Codable {
    let language: String
    let packVersion: String
    let sha256: String
    let bytes: Int
    let items: Int

    enum CodingKeys: String, CodingKey {
        case language, sha256, bytes, items
        case packVersion = "pack_version"
    }
}

enum PackManagerError: Error {
    case checksumMismatch
}

final class PackManager {
    /// e.g. https://github.com/<user>/maestro/releases/latest/download
    let baseURL: URL
    let installDir: URL

    init(baseURL: URL, installDir: URL) {
        self.baseURL = baseURL
        self.installDir = installDir
    }

    func checkForUpdate(installedVersion: String?) async throws -> ReleaseInfo? {
        let (data, _) = try await URLSession.shared.data(
            from: baseURL.appendingPathComponent("release.json"))
        let info = try JSONDecoder().decode(ReleaseInfo.self, from: data)
        return info.packVersion == installedVersion ? nil : info
    }

    func install(_ info: ReleaseInfo) async throws {
        let (temp, _) = try await URLSession.shared.download(
            from: baseURL.appendingPathComponent("\(info.language).pack.sqlite"))
        let digest = SHA256.hash(data: try Data(contentsOf: temp))
            .map { String(format: "%02x", $0) }.joined()
        guard digest == info.sha256 else { throw PackManagerError.checksumMismatch }
        let dest = installDir.appendingPathComponent("\(info.language).pack.sqlite")
        // Atomic swap; learner events reference items by stable id +
        // pack_version, so history stays interpretable across updates.
        _ = try FileManager.default.replaceItemAt(dest, withItemAt: temp)
    }
}
