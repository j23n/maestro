import Foundation
import ItalianCore

/// The bundled read-only content database (HANDOFF.md 6.2; schema in content/schema/content.sql).
public final class ContentDatabase: Sendable {
    public let db: SQLiteDatabase

    public init(path: String) throws {
        db = try SQLiteDatabase(path: path, readOnly: true)
    }

    public init(database: SQLiteDatabase) {
        db = database
    }

    public func meta(_ key: String) -> String? {
        (try? db.query("SELECT value FROM meta WHERE key = ?", [.text(key)]))?.first?.string("value")
    }

    /// Follows id_redirect (HANDOFF.md 6.5). Returns the ID unchanged when there is no redirect.
    public func resolve(_ id: String) -> String {
        var current = id
        for _ in 0..<5 {
            guard let next = (try? db.query("SELECT new_id FROM id_redirect WHERE old_id = ?", [.text(current)]))?
                .first?.string("new_id") else { return current }
            current = next
        }
        return current
    }

    /// The resolved ID if this database knows it, else nil (the card then renders from its snapshot).
    public func known(_ id: String) -> String? {
        let resolved = resolve(id)
        let table = resolved.contains("#") ? "sense" : "lemma"
        let rows = try? db.query("SELECT 1 FROM \(table) WHERE id = ?", [.text(resolved)])
        return (rows?.isEmpty == false) ? resolved : nil
    }

    // MARK: Lemmas and entries

    static let summaryColumns = """
        l.id, l.headword, l.pos, l.gender,
        (SELECT gloss FROM sense s WHERE s.lemma_id = l.id AND s.retired = 0 ORDER BY s.ord LIMIT 1) AS gloss
        """

    func summary(_ row: Row) -> LemmaSummary? {
        guard let id = row.string("id"), let headword = row.string("headword"), let pos = row.string("pos") else {
            return nil
        }
        return LemmaSummary(id: id, headword: headword, pos: pos, gender: row.string("gender"),
                            firstGloss: row.string("gloss") ?? "")
    }

    public func lemma(_ id: String) -> LemmaSummary? {
        let rows = try? db.query("SELECT \(Self.summaryColumns) FROM lemma l WHERE l.id = ?", [.text(resolve(id))])
        return rows?.first.flatMap(summary)
    }

    public func lemmas(headword: String) -> [LemmaSummary] {
        let rows = (try? db.query(
            "SELECT \(Self.summaryColumns) FROM lemma l WHERE l.headword = ? AND l.retired = 0 ORDER BY length(l.id), l.id",
            [.text(headword)])) ?? []
        return rows.compactMap(summary)
    }

    public func entry(_ id: String) -> Entry? {
        let lemmaID = resolve(id)
        guard let row = (try? db.query("SELECT * FROM lemma WHERE id = ?", [.text(lemmaID)]))?.first,
              let headword = row.string("headword"), let pos = row.string("pos") else { return nil }
        let senseRows = (try? db.query(
            "SELECT id, gloss, tags, retired FROM sense WHERE lemma_id = ? ORDER BY retired, ord", [.text(lemmaID)])) ?? []
        var senses: [Sense] = senseRows.compactMap { r in
            guard let sid = r.string("id"), let gloss = r.string("gloss") else { return nil }
            let tags = (r.string("tags") ?? "").split(separator: " ").map(String.init)
            return Sense(id: sid, lemmaID: lemmaID, gloss: gloss, tags: tags, retired: r.int("retired") == 1, examples: [])
        }
        for i in senses.indices {
            let ex = (try? db.query("SELECT it, en FROM example WHERE sense_id = ?", [.text(senses[i].id)])) ?? []
            senses[i].examples = ex.compactMap { r in r.string("it").map { Example(italian: $0, english: r.string("en")) } }
        }
        return Entry(id: lemmaID, headword: headword, pos: pos, gender: row.string("gender"), plural: row.string("plural"),
                     ipa: row.string("ipa"), auxiliary: row.string("auxiliary"), senses: senses)
    }

    public func sense(_ id: String) -> Sense? {
        let resolved = resolve(id)
        guard let r = (try? db.query("SELECT id, lemma_id, gloss, tags, retired FROM sense WHERE id = ?", [.text(resolved)]))?.first,
              let lemmaID = r.string("lemma_id"), let gloss = r.string("gloss") else { return nil }
        return Sense(id: resolved, lemmaID: lemmaID, gloss: gloss,
                     tags: (r.string("tags") ?? "").split(separator: " ").map(String.init),
                     retired: r.int("retired") == 1, examples: [])
    }

    /// Every form of a lemma with its tag ("" for the base form).
    public func forms(of lemmaID: String) -> [(form: String, tag: String)] {
        let rows = (try? db.query("SELECT form, tag FROM form WHERE lemma_id = ? ORDER BY rowid", [.text(resolve(lemmaID))])) ?? []
        return rows.compactMap { r in r.string("form").map { ($0, r.string("tag") ?? "") } }
    }

    /// (lemma, tag) pairs for an exact surface form.
    public func analyses(of form: String) -> [(lemma: LemmaSummary, tag: String)] {
        let rows = (try? db.query(
            "SELECT DISTINCT f.tag, \(Self.summaryColumns) FROM form f JOIN lemma l ON l.id = f.lemma_id "
                + "WHERE f.form = ? AND l.retired = 0", [.text(form)])) ?? []
        return rows.compactMap { r in summary(r).map { ($0, r.string("tag") ?? "") } }
    }

    /// Lemmas whose headword or forms match ignoring accents.
    public func foldedMatches(_ folded: String, limit: Int = 8) -> [LemmaSummary] {
        let rows = (try? db.query(
            "SELECT DISTINCT \(Self.summaryColumns) FROM lemma l WHERE l.retired = 0 AND (l.headword_fold = ? "
                + "OR l.id IN (SELECT lemma_id FROM form WHERE form_fold = ?)) ORDER BY length(l.headword) LIMIT ?",
            [.text(folded), .text(folded), .int(Int64(limit))])) ?? []
        return rows.compactMap(summary)
    }

    /// Full-text search: Italian headword prefix.
    public func prefixMatches(_ query: String, limit: Int = 12) -> [LemmaSummary] {
        let term = Self.ftsTerm(query)
        guard !term.isEmpty else { return [] }
        let rows = (try? db.query(
            "SELECT \(Self.summaryColumns) FROM lemma_fts JOIN lemma l ON l.id = lemma_fts.lemma_id "
                + "WHERE lemma_fts MATCH ? AND l.retired = 0 ORDER BY length(l.headword), rank LIMIT ?",
            [.text("headword:\(term)*"), .int(Int64(limit))])) ?? []
        return rows.compactMap(summary)
    }

    /// English to Italian over glosses (HANDOFF.md 3.2: weaker; curated words come first later).
    public func englishMatches(_ query: String, limit: Int = 20) -> [LemmaSummary] {
        let words = query.lowercased().split(whereSeparator: { !$0.isLetter }).map { Self.ftsTerm(String($0)) }
            .filter { !$0.isEmpty }
        guard !words.isEmpty else { return [] }
        let match = words.map { "glosses:\($0)" }.joined(separator: " AND ")
        let rows = (try? db.query(
            "SELECT \(Self.summaryColumns) FROM lemma_fts JOIN lemma l ON l.id = lemma_fts.lemma_id "
                + "WHERE lemma_fts MATCH ? AND l.retired = 0 ORDER BY rank LIMIT ?",
            [.text(match), .int(Int64(limit))])) ?? []
        return rows.compactMap(summary)
    }

    static func ftsTerm(_ s: String) -> String {
        String(s.filter { $0.isLetter || $0.isNumber })
    }

    // MARK: Grammar and catalog

    public func grammarTopics() -> [GrammarTopicRow] {
        let rows = (try? db.query("SELECT id, title, level, summary, body FROM grammar_topic ORDER BY ord, id")) ?? []
        return rows.compactMap(GrammarTopicRow.init)
    }

    public func grammarTopic(_ id: String) -> GrammarTopicRow? {
        let rows = try? db.query("SELECT id, title, level, summary, body FROM grammar_topic WHERE id = ?",
                                 [.text(resolve(id))])
        return rows?.first.flatMap(GrammarTopicRow.init)
    }

    /// lemma -> count for every catalogued text, for Known % on texts not yet downloaded.
    public func textLemmas() -> [String: [String: Int]] {
        let rows = (try? db.query("SELECT text_id, lemma_id, count FROM text_lemma")) ?? []
        var result: [String: [String: Int]] = [:]
        for r in rows {
            guard let t = r.string("text_id"), let l = r.string("lemma_id"), let c = r.int("count") else { continue }
            result[t, default: [:]][l] = c
        }
        return result
    }
}

public struct GrammarTopicRow: Sendable, Hashable, Identifiable {
    public let id: String
    public let title: String
    public let level: String
    public let summary: String
    public let body: String

    init?(_ row: Row) {
        guard let id = row.string("id"), let title = row.string("title") else { return nil }
        self.id = id
        self.title = title
        level = row.string("level") ?? ""
        summary = row.string("summary") ?? ""
        body = row.string("body") ?? ""
    }
}
