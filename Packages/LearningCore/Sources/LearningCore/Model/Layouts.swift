import Foundation

/// A string in a real-world layout: Italian (tokenized, tappable) or plain (prices, times, `ignore` entries).
public enum LayoutString: Codable, Sendable, Hashable {
    case italian(TokenizedText)
    case plain(String)

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let s = try? c.decode(String.self) {
            self = .plain(s)
        } else {
            self = .italian(try c.decode(TokenizedText.self))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .italian(let t): try c.encode(t)
        case .plain(let s): try c.encode(s)
        }
    }

    public var text: String {
        switch self {
        case .italian(let t): t.text
        case .plain(let s): s
        }
    }
}

/// `texts.layout` for real-world texts (docs/06 §4): one case per layout type, drawn natively by the app.
public enum LayoutPayload: Codable, Sendable, Hashable {
    public struct MenuRow: Codable, Sendable, Hashable {
        public let name: LayoutString
        public let price: LayoutString
        public let note: LayoutString?
    }

    public struct MenuSection: Codable, Sendable, Hashable {
        public let title: LayoutString
        public let rows: [MenuRow]
    }

    public struct ReceiptRow: Codable, Sendable, Hashable {
        public let name: LayoutString
        public let qty: LayoutString?
        public let price: LayoutString
    }

    public struct HoursRow: Codable, Sendable, Hashable {
        public let days: LayoutString
        public let times: LayoutString
    }

    public struct Field: Codable, Sendable, Hashable {
        public let label: LayoutString
        public let value: LayoutString
    }

    case menu(title: LayoutString, sections: [MenuSection])
    case receipt(shop: LayoutString, rows: [ReceiptRow], total: LayoutString, footer: LayoutString?)
    case sign(lines: [LayoutString], style: String)
    case hours(title: LayoutString, rows: [HoursRow], note: LayoutString?)
    case timetable(title: LayoutString, columns: [LayoutString], rows: [[LayoutString]])
    case fields(type: String, title: LayoutString, fields: [Field])  // ticket, form, label
    case ad(title: LayoutString, body: [LayoutString], contact: LayoutString?)
    case message(from: LayoutString, time: LayoutString?, bubbles: [LayoutString])
    case postcard(greeting: LayoutString, body: [LayoutString], closing: LayoutString, signature: LayoutString,
                  address: [LayoutString]?)
    case list(title: LayoutString?, items: [LayoutString])

    private enum K: String, CodingKey {
        case type, title, sections, shop, rows, total, footer, lines, style, note, columns, fields, body, contact
        case from, time, bubbles, greeting, closing, signature, address, items
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: K.self)
        let type = try c.decode(String.self, forKey: .type)
        func s(_ k: K) throws -> LayoutString { try c.decode(LayoutString.self, forKey: k) }
        func o(_ k: K) throws -> LayoutString? { try c.decodeIfPresent(LayoutString.self, forKey: k) }
        func a(_ k: K) throws -> [LayoutString] { try c.decode([LayoutString].self, forKey: k) }
        switch type {
        case "menu": self = .menu(title: try s(.title), sections: try c.decode([MenuSection].self, forKey: .sections))
        case "receipt":
            self = .receipt(shop: try s(.shop), rows: try c.decode([ReceiptRow].self, forKey: .rows),
                            total: try s(.total), footer: try o(.footer))
        case "sign": self = .sign(lines: try a(.lines), style: try c.decodeIfPresent(String.self, forKey: .style) ?? "info")
        case "hours": self = .hours(title: try s(.title), rows: try c.decode([HoursRow].self, forKey: .rows), note: try o(.note))
        case "timetable":
            self = .timetable(title: try s(.title), columns: try a(.columns),
                              rows: try c.decode([[LayoutString]].self, forKey: .rows))
        case "ticket", "form", "label":
            self = .fields(type: type, title: try s(.title), fields: try c.decode([Field].self, forKey: .fields))
        case "ad": self = .ad(title: try s(.title), body: try a(.body), contact: try o(.contact))
        case "message":
            self = .message(from: try s(.from), time: try o(.time), bubbles: try a(.bubbles))
        case "postcard":
            self = .postcard(greeting: try s(.greeting), body: try a(.body), closing: try s(.closing),
                             signature: try s(.signature), address: try c.decodeIfPresent([LayoutString].self, forKey: .address))
        case "list": self = .list(title: try o(.title), items: try a(.items))
        default:
            throw DecodingError.dataCorruptedError(forKey: .type, in: c, debugDescription: "unknown layout \(type)")
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: K.self)
        switch self {
        case .menu(let t, let s):
            try c.encode("menu", forKey: .type)
            try c.encode(t, forKey: .title)
            try c.encode(s, forKey: .sections)
        case .receipt(let shop, let rows, let total, let footer):
            try c.encode("receipt", forKey: .type)
            try c.encode(shop, forKey: .shop)
            try c.encode(rows, forKey: .rows)
            try c.encode(total, forKey: .total)
            try c.encode(footer, forKey: .footer)
        case .sign(let lines, let style):
            try c.encode("sign", forKey: .type)
            try c.encode(lines, forKey: .lines)
            try c.encode(style, forKey: .style)
        case .hours(let t, let r, let n):
            try c.encode("hours", forKey: .type)
            try c.encode(t, forKey: .title)
            try c.encode(r, forKey: .rows)
            try c.encode(n, forKey: .note)
        case .timetable(let t, let cols, let rows):
            try c.encode("timetable", forKey: .type)
            try c.encode(t, forKey: .title)
            try c.encode(cols, forKey: .columns)
            try c.encode(rows, forKey: .rows)
        case .fields(let type, let t, let f):
            try c.encode(type, forKey: .type)
            try c.encode(t, forKey: .title)
            try c.encode(f, forKey: .fields)
        case .ad(let t, let b, let contact):
            try c.encode("ad", forKey: .type)
            try c.encode(t, forKey: .title)
            try c.encode(b, forKey: .body)
            try c.encode(contact, forKey: .contact)
        case .message(let from, let time, let bubbles):
            try c.encode("message", forKey: .type)
            try c.encode(from, forKey: .from)
            try c.encode(time, forKey: .time)
            try c.encode(bubbles, forKey: .bubbles)
        case .postcard(let g, let b, let cl, let sig, let addr):
            try c.encode("postcard", forKey: .type)
            try c.encode(g, forKey: .greeting)
            try c.encode(b, forKey: .body)
            try c.encode(cl, forKey: .closing)
            try c.encode(sig, forKey: .signature)
            try c.encode(addr, forKey: .address)
        case .list(let t, let items):
            try c.encode("list", forKey: .type)
            try c.encode(t, forKey: .title)
            try c.encode(items, forKey: .items)
        }
    }
}
