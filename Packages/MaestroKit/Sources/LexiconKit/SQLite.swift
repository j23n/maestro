import CSQLite
import Foundation

public enum SQLiteError: Error, CustomStringConvertible {
    case open(String)
    case prepare(String, sql: String)
    case step(String)

    public var description: String {
        switch self {
        case .open(let m): "SQLite open failed: \(m)"
        case .prepare(let m, let sql): "SQLite prepare failed: \(m) in \(sql)"
        case .step(let m): "SQLite step failed: \(m)"
        }
    }
}

public enum SQLValue: Sendable, Hashable {
    case null
    case int(Int64)
    case double(Double)
    case text(String)
}

extension SQLValue: ExpressibleByStringLiteral, ExpressibleByIntegerLiteral {
    public init(stringLiteral value: String) { self = .text(value) }
    public init(integerLiteral value: Int) { self = .int(Int64(value)) }
}

/// One result row, addressed by column name.
public struct Row: Sendable {
    let columns: [String: Int]
    let values: [SQLValue]

    public subscript(_ name: String) -> SQLValue {
        guard let i = columns[name] else { return .null }
        return values[i]
    }

    public func string(_ name: String) -> String? {
        switch self[name] {
        case .text(let s): s
        case .int(let i): String(i)
        case .double(let d): String(d)
        case .null: nil
        }
    }

    public func int(_ name: String) -> Int? {
        switch self[name] {
        case .int(let i): Int(i)
        case .double(let d): Int(d)
        case .text(let s): Int(s)
        case .null: nil
        }
    }
}

/// SQLITE_TRANSIENT, which C defines as a cast Swift can't import: SQLite copies the bound text.
private func transientDestructor() -> sqlite3_destructor_type {
    unsafeBitCast(OpaquePointer(bitPattern: -1), to: sqlite3_destructor_type.self)
}

/// A minimal SQLite connection. Serialised with a lock, so it can be shared across tasks.
public final class SQLiteDatabase: @unchecked Sendable {
    private let handle: OpaquePointer
    private let lock = NSLock()

    public init(path: String, readOnly: Bool = true) throws {
        var db: OpaquePointer?
        let flags = (readOnly ? SQLITE_OPEN_READONLY : (SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE)) | SQLITE_OPEN_FULLMUTEX
        let rc = sqlite3_open_v2(path, &db, flags, nil)
        guard rc == SQLITE_OK, let db else {
            let message = db.map { String(cString: sqlite3_errmsg($0)) } ?? "code \(rc)"
            if let db { sqlite3_close(db) }
            throw SQLiteError.open(message)
        }
        handle = db
    }

    /// An in-memory database, for tests.
    public static func inMemory() throws -> SQLiteDatabase {
        try SQLiteDatabase(path: ":memory:", readOnly: false)
    }

    deinit {
        sqlite3_close(handle)
    }

    public func execute(_ sql: String) throws {
        lock.lock()
        defer { lock.unlock() }
        var error: UnsafeMutablePointer<CChar>?
        if sqlite3_exec(handle, sql, nil, nil, &error) != SQLITE_OK {
            let message = error.map { String(cString: $0) } ?? "unknown"
            sqlite3_free(error)
            throw SQLiteError.step(message)
        }
    }

    public func query(_ sql: String, _ arguments: [SQLValue] = []) throws -> [Row] {
        lock.lock()
        defer { lock.unlock() }
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK, let statement else {
            throw SQLiteError.prepare(String(cString: sqlite3_errmsg(handle)), sql: sql)
        }
        defer { sqlite3_finalize(statement) }
        let transient = transientDestructor()
        for (i, value) in arguments.enumerated() {
            let index = Int32(i + 1)
            switch value {
            case .null: sqlite3_bind_null(statement, index)
            case .int(let v): sqlite3_bind_int64(statement, index, v)
            case .double(let v): sqlite3_bind_double(statement, index, v)
            case .text(let v): sqlite3_bind_text(statement, index, v, -1, transient)
            }
        }
        let count = Int(sqlite3_column_count(statement))
        var columns: [String: Int] = [:]
        for i in 0..<count {
            columns[String(cString: sqlite3_column_name(statement, Int32(i)))] = i
        }
        var rows: [Row] = []
        while true {
            let rc = sqlite3_step(statement)
            if rc == SQLITE_DONE { break }
            guard rc == SQLITE_ROW else { throw SQLiteError.step(String(cString: sqlite3_errmsg(handle))) }
            var values: [SQLValue] = []
            values.reserveCapacity(count)
            for i in 0..<count {
                let col = Int32(i)
                switch sqlite3_column_type(statement, col) {
                case SQLITE_INTEGER: values.append(.int(sqlite3_column_int64(statement, col)))
                case SQLITE_FLOAT: values.append(.double(sqlite3_column_double(statement, col)))
                case SQLITE_NULL: values.append(.null)
                default:
                    if let text = sqlite3_column_text(statement, col) {
                        values.append(.text(String(cString: text)))
                    } else {
                        values.append(.null)
                    }
                }
            }
            rows.append(Row(columns: columns, values: values))
        }
        return rows
    }
}
