import Foundation

/// The pack's `meta` table (docs/04 § Pack build), read and checked when the reader opens.
public struct PackMeta: Sendable, Hashable {
    /// `schema_version`: equals `PackReader.schemaVersion`, or the pack is refused.
    public let schemaVersion: Int
    /// `pack_version` (semver from `course.yaml`); every event records it.
    public let packVersion: String
    /// `content_hash`: the canonical pack hash. A change triggers `rebuildAll()` at launch (docs/05 § Replay).
    public let contentHash: String
    /// `course_id`, e.g. `italiano-a1`.
    public let courseId: String
    /// `locale`, e.g. `it-IT`.
    public let locale: String
    /// `release`: 1 for release packs (approved content only), 0 for dev packs (drafts included).
    public let isRelease: Bool
    /// `git_sha` and `built_with`: informational, outside the pack hash.
    public let gitSha: String?
    public let builtWith: String?
    /// `review_files` (dev packs, review mode): JSON `{"<id prefix>": {"file": "content/…yaml", "hash": "…"}}`,
    /// decoded by the App's `ReviewFileIndex` (docs/04 § Content review loop › 2).
    public let reviewFilesJSON: String?
    /// Every row, including keys this reader doesn't know.
    public let values: [String: String]

    /// The keys a pack must have; `git_sha`, `built_with` and `review_files` are optional.
    static let requiredKeys = ["schema_version", "pack_version", "content_hash", "course_id", "locale", "release"]

    /// Parses the rows; throws `schemaMismatch` before looking at anything else, so a newer pack whose other keys
    /// changed still reports the mismatch.
    init(values: [String: String], path: String, supportedSchema: Int) throws(PackError) {
        guard let raw = values["schema_version"] else {
            throw .notAContentPack(path: path, reason: "meta.schema_version is missing")
        }
        guard let version = Int(raw.trimmingCharacters(in: .whitespaces)) else {
            throw .notAContentPack(path: path, reason: "meta.schema_version is not an integer: \(raw)")
        }
        guard version == supportedSchema else { throw .schemaMismatch(pack: version, app: supportedSchema) }
        let missing = Self.requiredKeys.filter { values[$0] == nil }
        guard missing.isEmpty else {
            throw .notAContentPack(path: path, reason: "meta is missing \(missing.joined(separator: ", "))")
        }
        let release = values["release", default: ""]
        guard release == "0" || release == "1" else {
            throw .notAContentPack(path: path, reason: "meta.release must be 0 or 1, not \(release)")
        }
        schemaVersion = version
        packVersion = values["pack_version", default: ""]
        contentHash = values["content_hash", default: ""]
        courseId = values["course_id", default: ""]
        locale = values["locale", default: ""]
        isRelease = release == "1"
        gitSha = values["git_sha"]
        builtWith = values["built_with"]
        reviewFilesJSON = values["review_files"]
        self.values = values
    }
}
