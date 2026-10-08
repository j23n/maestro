import Foundation

// A minimal ZIP writer for the examiner export (docs/12 § Final check export): every file is stored, not
// compressed (the recordings are already compressed m4a and the text files are tiny), so the format is a few
// fixed-size headers and a CRC-32 per file. No third-party library and no platform API, so it is tested on Linux.
// PKWARE APPNOTE 6.3.x: local file headers, the central directory, the end-of-central-directory record; names are
// UTF-8 (flag bit 11); no ZIP64 (the export is a few MB at most).

enum StoredZip {
    struct Entry: Sendable, Equatable {
        /// The path inside the archive, with `/` between folders (`speaking/final.s01-….m4a`).
        let path: String
        let data: Data
    }

    enum Failure: Error, Equatable {
        case tooLarge
        case badPath(String)
    }

    /// The archive's bytes. `modified` (with the learner's UTC offset) is every entry's date, so the same input
    /// always gives the same bytes.
    static func archive(_ entries: [Entry], modified ms: Int64, tzOffsetMinutes: Int) throws(Failure) -> Data {
        guard entries.count < 0xFFFF else { throw .tooLarge }
        let (time, date) = dosDateTime(ms: ms, tzOffsetMinutes: tzOffsetMinutes)
        var out = Data()
        var central = Data()
        for entry in entries {
            let name = Data(entry.path.utf8)
            guard !entry.path.isEmpty, !entry.path.hasPrefix("/"), !entry.path.contains("\\"),
                !entry.path.split(separator: "/").contains(".."), name.count < 0xFFFF
            else { throw .badPath(entry.path) }
            let offset = out.count
            let size = entry.data.count
            guard size < 0xFFFF_FFFF, offset < 0xFFFF_FFFF else { throw .tooLarge }
            let crc = CRC32.checksum(entry.data)
            // Local file header.
            out.append(le32: 0x0403_4B50)
            out.append(le16: 20)  // version needed: 2.0
            out.append(le16: 0x0800)  // UTF-8 names
            out.append(le16: 0)  // stored
            out.append(le16: time)
            out.append(le16: date)
            out.append(le32: crc)
            out.append(le32: UInt32(size))
            out.append(le32: UInt32(size))
            out.append(le16: UInt16(name.count))
            out.append(le16: 0)
            out.append(name)
            out.append(entry.data)
            // Central directory header.
            central.append(le32: 0x0201_4B50)
            central.append(le16: 0x0314)  // made by: Unix, 2.0 (so the permissions below apply)
            central.append(le16: 20)
            central.append(le16: 0x0800)
            central.append(le16: 0)
            central.append(le16: time)
            central.append(le16: date)
            central.append(le32: crc)
            central.append(le32: UInt32(size))
            central.append(le32: UInt32(size))
            central.append(le16: UInt16(name.count))
            central.append(le16: 0)  // extra
            central.append(le16: 0)  // comment
            central.append(le16: 0)  // disk
            central.append(le16: 0)  // internal attributes
            central.append(le32: 0o100644 << 16)  // a regular file, rw-r--r--
            central.append(le32: UInt32(offset))
            central.append(name)
        }
        let centralOffset = out.count
        guard centralOffset < 0xFFFF_FFFF, central.count < 0xFFFF_FFFF else { throw .tooLarge }
        out.append(central)
        // End of central directory.
        out.append(le32: 0x0605_4B50)
        out.append(le16: 0)
        out.append(le16: 0)
        out.append(le16: UInt16(entries.count))
        out.append(le16: UInt16(entries.count))
        out.append(le32: UInt32(central.count))
        out.append(le32: UInt32(centralOffset))
        out.append(le16: 0)
        return out
    }

    /// MS-DOS time and date fields of a local time (2-second resolution, years 1980–2107).
    static func dosDateTime(ms: Int64, tzOffsetMinutes: Int) -> (time: UInt16, date: UInt16) {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: tzOffsetMinutes * 60) ?? TimeZone(secondsFromGMT: 0) ?? .current
        let c = calendar.dateComponents(
            [.year, .month, .day, .hour, .minute, .second],
            from: Date(timeIntervalSince1970: Double(ms) / 1000))
        let year = min(max((c.year ?? 1980) - 1980, 0), 127)
        let time = UInt16((c.hour ?? 0) << 11 | (c.minute ?? 0) << 5 | (c.second ?? 0) / 2)
        let date = UInt16(year << 9 | (c.month ?? 1) << 5 | (c.day ?? 1))
        return (time, date)
    }
}

/// CRC-32 (IEEE 802.3, reflected polynomial 0xEDB88320), as ZIP uses it.
enum CRC32 {
    static let table: [UInt32] = (0..<256).map { n -> UInt32 in
        var c = UInt32(n)
        for _ in 0..<8 { c = c & 1 == 1 ? 0xEDB8_8320 ^ (c >> 1) : c >> 1 }
        return c
    }

    static func checksum(_ data: Data) -> UInt32 {
        var crc: UInt32 = 0xFFFF_FFFF
        for byte in data { crc = table[Int((crc ^ UInt32(byte)) & 0xFF)] ^ (crc >> 8) }
        return crc ^ 0xFFFF_FFFF
    }
}

extension Data {
    fileprivate mutating func append(le16 v: UInt16) {
        append(UInt8(v & 0xFF))
        append(UInt8(v >> 8))
    }

    fileprivate mutating func append(le32 v: UInt32) {
        for shift in stride(from: 0, to: 32, by: 8) { append(UInt8((v >> UInt32(shift)) & 0xFF)) }
    }
}
