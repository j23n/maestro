import Foundation
import GRDB
import LearningCore

/// The read-only content pack (docs/02 § Storage): `content.sqlite` from the bundle, opened with a GRDB
/// `DatabaseQueue` and `Configuration.readonly` (never a pool: the bundle is read-only and the pack is built with
/// `journal_mode=DELETE`, so WAL can't be used).
///
/// Opening checks that the file is a pack this app reads: `meta.schema_version` must equal `schemaVersion`
/// (else `PackError.schemaMismatch`), the required meta keys and every table of `schemas/content-pack.sql` must
/// exist, and every query below must prepare against the tables (else `PackError.notAContentPack`).
///
/// Queries are `async` and run on GRDB's serial queue, never on the caller's actor; they return Sendable values.
/// JSON columns are decoded into LearningCore's payload types and checked against their row (a payload that
/// contradicts its columns is a `malformedRow`). The pack never changes while the app runs, so callers may keep
/// what they read (`contentIndex()`, `knownForms()`, `audioCatalog()`, `searchIndex()`) for the app's lifetime.
public final class PackReader: Sendable {
    /// The `meta.schema_version` this build reads. Bump it with `schemas/content-pack.sql`.
    public static let schemaVersion = 1

    /// Every table of `schemas/content-pack.sql`.
    static let tables: [String] = [
        "meta", "units", "can_dos", "syllabus_items", "syllabus_trace", "audio", "items", "item_skills",
        "item_requires", "forms", "sounds", "characters", "countries", "lessons", "steps", "step_introduces", "texts",
        "text_lines", "tokens", "text_requires", "grammar_notes", "note_items", "exercises", "exercise_targets",
        "exercise_requires", "assessments", "exercise_tags",
    ]

    /// The pack file.
    public let url: URL
    /// `Content/Audio/`: where `audio.file` names live.
    public let audioDirectory: URL
    /// The pack's `meta`, checked at open.
    public let meta: PackMeta
    let queue: DatabaseQueue

    /// Opens and checks the pack. `audioDirectory` defaults to `Audio/` next to the pack file (the bundle's
    /// `Content/content.sqlite` and `Content/Audio/`). Opening reads a few rows and prepares the statements (a few
    /// milliseconds); call it off the main actor, or use `open(url:audioDirectory:)`.
    public init(url: URL, audioDirectory: URL? = nil) throws(PackError) {
        let path = url.path
        guard FileManager.default.fileExists(atPath: path) else {
            StorageLog.packFailed(.fileMissing(path: path))
            throw .fileMissing(path: path)
        }
        var config = Configuration()
        config.readonly = true
        config.label = "content-pack"
        do {
            let queue = try DatabaseQueue(path: path, configuration: config)
            meta = try queue.read { db in try Self.check(db, path: path) }
            self.queue = queue
        } catch {
            let packError = Self.openError(error, path: path)
            StorageLog.packFailed(packError)
            throw packError
        }
        self.url = url
        self.audioDirectory = audioDirectory ?? url.deletingLastPathComponent().appendingPathComponent("Audio")
    }

    /// Opens and checks the pack off the caller's actor.
    @concurrent
    public static func open(url: URL, audioDirectory: URL? = nil) async throws(PackError) -> PackReader {
        try PackReader(url: url, audioDirectory: audioDirectory)
    }

    /// The checks at open: meta (schema version first), tables, then every statement prepares.
    private static func check(_ db: Database, path: String) throws -> PackMeta {
        let metaRows: [Row]
        do {
            metaRows = try Row.fetchAll(db, sql: "SELECT key, value FROM meta")
        } catch {
            throw PackError.notAContentPack(path: path, reason: "no readable meta table (\(error))")
        }
        var values: [String: String] = [:]
        for row in metaRows {
            let key: String? = try? row.decode(forColumn: "key")
            let value: String? = try? row.decode(forColumn: "value")
            if let key, let value { values[key] = value }
        }
        let meta = try PackMeta(values: values, path: path, supportedSchema: schemaVersion)
        let present = Set(try String.fetchAll(db, sql: "SELECT name FROM sqlite_master WHERE type = 'table'"))
        let missing = tables.filter { !present.contains($0) }
        guard missing.isEmpty else {
            throw PackError.notAContentPack(path: path, reason: "missing tables: \(missing.joined(separator: ", "))")
        }
        for sql in PackSQL.all {
            do {
                _ = try db.cachedStatement(sql: sql)
            } catch {
                throw PackError.notAContentPack(path: path, reason: "a query doesn't fit the tables: \(error)")
            }
        }
        return meta
    }

    private static func openError(_ error: any Error, path: String) -> PackError {
        switch error {
        case let e as PackError: e
        default: .notAContentPack(path: path, reason: String(describing: error))
        }
    }

    /// Runs `body` on the pack's queue and maps every error to a `PackError`.
    func read<T: Sendable>(_ body: @Sendable (Database) throws -> T) async throws(PackError) -> T {
        do {
            return try await queue.read(body)
        } catch {
            throw PackError.wrap(error)
        }
    }
}

// MARK: - Statements

extension Database {
    /// Rows of a cached (prepared once per connection) statement.
    func packRows(_ sql: String, _ arguments: StatementArguments = []) throws -> [Row] {
        try Row.fetchAll(cachedStatement(sql: sql), arguments: arguments)
    }

    func packRow(_ sql: String, _ arguments: StatementArguments = []) throws -> Row? {
        try Row.fetchOne(cachedStatement(sql: sql), arguments: arguments)
    }
}

/// Typed, throwing column access for one row: every failure is a `malformedRow` naming the table, row and column.
struct PackRow {
    let row: Row
    let table: String
    let id: String

    init(_ row: Row, table: String, id: String? = nil) {
        self.row = row
        self.table = table
        self.id = id ?? ((try? row.decode(String?.self, forColumn: "id")).flatMap { $0 } ?? "?")
    }

    func fail(_ reason: String) -> PackError { .malformedRow(table: table, id: id, reason: reason) }

    private func value<V: DatabaseValueConvertible>(_ column: String) throws(PackError) -> V {
        do {
            return try row.decode(V.self, forColumn: column)
        } catch {
            throw fail("\(column): \(error)")
        }
    }

    func string(_ column: String) throws(PackError) -> String { try value(column) }
    func optString(_ column: String) throws(PackError) -> String? { try value(column) }
    func int(_ column: String) throws(PackError) -> Int { try value(column) }
    func optInt(_ column: String) throws(PackError) -> Int? { try value(column) }

    func bool(_ column: String) throws(PackError) -> Bool {
        let v = try int(column)
        guard v == 0 || v == 1 else { throw fail("\(column): \(v) is not 0 or 1") }
        return v == 1
    }

    func id<Tag>(_ column: String) throws(PackError) -> TypedID<Tag> { TypedID(try string(column)) }
    func optID<Tag>(_ column: String) throws(PackError) -> TypedID<Tag>? {
        try optString(column).map { TypedID(rawValue: $0) }
    }

    func enumValue<E: RawRepresentable>(_ column: String, as _: E.Type = E.self) throws(PackError) -> E
    where E.RawValue == String {
        let raw = try string(column)
        guard let v = E(rawValue: raw) else { throw fail("\(column): unknown value \(raw)") }
        return v
    }

    func optEnum<E: RawRepresentable>(_ column: String, as _: E.Type = E.self) throws(PackError) -> E?
    where E.RawValue == String {
        guard let raw = try optString(column) else { return nil }
        guard let v = E(rawValue: raw) else { throw fail("\(column): unknown value \(raw)") }
        return v
    }

    func json<T: Decodable>(_ column: String, as _: T.Type = T.self) throws(PackError) -> T {
        try decodeJSON(try string(column), column: column)
    }

    func optJSON<T: Decodable>(_ column: String, as _: T.Type = T.self) throws(PackError) -> T? {
        guard let text = try optString(column) else { return nil }
        return try decodeJSON(text, column: column)
    }

    private func decodeJSON<T: Decodable>(_ text: String, column: String) throws(PackError) -> T {
        do {
            return try JSONDecoder().decode(T.self, from: Data(text.utf8))
        } catch {
            throw fail("\(column): \(Self.describe(error))")
        }
    }

    /// A short, readable decoding error: the coding path and what went wrong.
    static func describe(_ error: any Error) -> String {
        guard let e = error as? DecodingError else { return String(describing: error) }
        func path(_ c: DecodingError.Context) -> String {
            let p = c.codingPath.map { $0.intValue.map { "[\($0)]" } ?? ".\($0.stringValue)" }.joined()
            return p.isEmpty ? "" : "at \(p): "
        }
        switch e {
        case .keyNotFound(let key, let c): return "\(path(c))missing key \(key.stringValue)"
        case .valueNotFound(_, let c), .typeMismatch(_, let c), .dataCorrupted(let c):
            return "\(path(c))\(c.debugDescription)"
        @unknown default: return String(describing: e)
        }
    }
}
