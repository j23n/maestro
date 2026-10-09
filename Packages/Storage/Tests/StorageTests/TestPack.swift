import Foundation
import GRDB
import LearningCore

@testable import Storage

/// Repo-root files, found from this file's path (SwiftPM can't bundle files outside a package; docs/10), or from
/// `ITALIANO_ROOT` when the tests run from a copy of the package.
enum Repo {
    static let root: URL = {
        if let env = ProcessInfo.processInfo.environment["ITALIANO_ROOT"], !env.isEmpty {
            return URL(fileURLWithPath: env)
        }
        var url = URL(fileURLWithPath: #filePath)
        // …/Packages/Storage/Tests/StorageTests/TestPack.swift → the repo root is five levels up.
        for _ in 0..<5 { url.deleteLastPathComponent() }
        return url
    }()

    static func url(_ relative: String) -> URL { root.appendingPathComponent(relative) }
}

/// A small content pack built at test time: `schemas/content-pack.sql` plus rows whose JSON comes from
/// `fixtures/packs/payload-examples.json` (every exercise, step, note, assessment and layout example), with a few
/// items, texts, tokens and audio rows around them. The examples name some exercises they don't define (story
/// questions 2–3, the preview's generated exercises, the task conversation…); those are copies of an example of the
/// right format under the named ID, so every reference in the pack resolves.
enum TestPack {
    /// Parsed on each access ([String: Any] isn't Sendable, so it can't be a shared constant); the file is small.
    static var examples: [String: Any] {
        guard let data = try? Data(contentsOf: Repo.url("fixtures/packs/payload-examples.json")),
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { fatalError("fixtures/packs/payload-examples.json is missing or invalid") }
        return object
    }

    static var exampleExercises: [[String: Any]] { examples["exercises"] as? [[String: Any]] ?? [] }
    static var exampleSteps: [[String: Any]] { examples["steps"] as? [[String: Any]] ?? [] }
    static var exampleNote: [String: Any] { (examples["notes"] as? [[String: Any]])?.first ?? [:] }
    static var exampleAssessments: [[String: Any]] { examples["assessments"] as? [[String: Any]] ?? [] }
    static var exampleLayout: [String: Any] { (examples["layouts"] as? [[String: Any]])?.first ?? [:] }

    /// The step ID each example step payload gets, by kind.
    static let stepIDs: [String: (id: String, lesson: String?, ord: Int, strand: String)] = [
        "opener": ("u02.step-opener", nil, 1, "input"),
        "preview": ("u02.l1.step-preview", "u02.l1", 2, "language-focus"),
        "story": ("u02.l1.step-story", "u02.l1", 3, "input"),
        "note": ("u02.l1.step-note", "u02.l1", 4, "language-focus"),
        "practice": ("u02.l1.step-practice", "u02.l1", 5, "language-focus"),
        "sounds": ("u02.l1.step-sounds", "u02.l1", 6, "language-focus"),
        "use": ("u02.l1.step-use", "u02.l1", 7, "output"),
        "listening": ("u02.l2.step-listening", "u02.l2", 8, "input"),
        "reading": ("u02.l2.step-reading", "u02.l2", 9, "input"),
        "conversation": ("u02.step-conversation-1", nil, 10, "output"),
        "talk": ("u02.step-talk", nil, 11, "output"),
        "relay": ("u02.step-relay", nil, 12, "output"),
        "check": ("u02.step-check", nil, 13, "assessment"),
        "fluency": ("u02.step-fluency", nil, 14, "fluency"),
    ]

    /// Exercises the examples name but don't define: (new ID, example to copy, step, role).
    static let copies: [(id: String, from: String, step: String, role: String?)] = [
        ("u02.l1.q2", "u02.l1.q1", "u02.l1.step-story", nil),
        ("u02.l1.q3", "u02.l1.q1", "u02.l1.step-story", nil),
        ("u02.l1.ex15", "u02.l1.ex10", "u02.l1.step-practice", nil),
        ("u02.l1.ex24", "u02.l1.ex22", "u02.l1.step-sounds", nil),
        ("u02.l1.step-preview.b1.match", "u02.l1.ex20", "u02.l1.step-preview", nil),
        ("u02.l1.step-preview.b1.w-caffe", "u02.l1.ex04", "u02.l1.step-preview", nil),
        ("u02.l1.step-preview.b1.c-vorrei", "u02.l1.ex04", "u02.l1.step-preview", nil),
        ("u02.l2.ex20", "u02.check.03", "u02.l2.step-listening", "learn"),
        ("u02.l2.ex21", "u02.l1.q1", "u02.l2.step-reading", "learn"),
        ("u02.task.conv1", "u02.l1.ex25", "u02.step-conversation-1", nil),
        ("u02.check.02", "u02.check.01", "u02.step-check", nil),
    ]

    /// IDs of the example exercises (as authored in the fixture).
    static var exampleExerciseIDs: [String] { exampleExercises.compactMap { $0["id"] as? String } }

    /// One directory per test process; directories left by runs more than an hour old are removed.
    static let workDirectory: URL = {
        let fm = FileManager.default
        let tmp = fm.temporaryDirectory
        let prefix = "storage-tests-"
        let stale = Date().addingTimeInterval(-3_600)
        for name in (try? fm.contentsOfDirectory(atPath: tmp.path)) ?? [] where name.hasPrefix(prefix) {
            let url = tmp.appendingPathComponent(name)
            let modified = (try? fm.attributesOfItem(atPath: url.path)[.modificationDate]) as? Date
            if let modified, modified < stale { try? fm.removeItem(at: url) }
        }
        return tmp.appendingPathComponent("\(prefix)\(ProcessInfo.processInfo.processIdentifier)", isDirectory: true)
    }()

    static let storyAudio = "a:000000000001"
    static let cornettoAudio = "a:000000000002"
    static let checkAudio = "a:000000000003"

    /// Builds a fresh pack and returns its URL. `meta` overrides meta rows (nil removes one); `adjust` runs last,
    /// with foreign keys still on, to break the pack in a specific way.
    static func build(meta: [String: String?] = [:], adjust: ((Database) throws -> Void)? = nil) throws -> URL {
        let dir = workDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent("content.sqlite")
        let ddl = try String(contentsOf: Repo.url("schemas/content-pack.sql"), encoding: .utf8)
        let queue = try DatabaseQueue(path: url.path)
        try queue.writeWithoutTransaction { db in try db.execute(sql: ddl) }
        try queue.write { db in
            try fill(db, meta: meta)
            try adjust?(db)
        }
        try queue.close()
        return url
    }

    static func json(_ object: Any) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
            let text = String(data: data, encoding: .utf8)
        else { fatalError("not JSON: \(object)") }
        return text
    }

    static func insert(_ db: Database, _ table: String, _ rows: [[String: (any DatabaseValueConvertible)?]]) throws {
        for row in rows {
            let columns = row.keys.sorted()
            let sql = "INSERT INTO \(table) (\(columns.joined(separator: ", "))) VALUES "
                + "(\(columns.map { _ in "?" }.joined(separator: ", ")))"
            try db.execute(sql: sql, arguments: StatementArguments(columns.map { row[$0] ?? nil }))
        }
    }

    private static func fill(_ db: Database, meta overrides: [String: String?]) throws {
        var meta: [String: String?] = [
            "schema_version": "\(PackReader.schemaVersion)", "pack_version": "0.1.0", "content_hash": "test-hash",
            "git_sha": "abc123", "built_with": "storage-tests", "course_id": "italiano-a1", "locale": "it-IT",
            "release": "0",
            "review_files": #"{"u02.l1": {"file": "content/units/02-al-bar/lesson-1.yaml", "hash": "h1"}}"#,
        ]
        meta.merge(overrides) { _, new in new }
        try insert(db, "meta", meta.compactMap { k, v in v.map { ["key": k, "value": $0] } })

        try insert(db, "units", [
            ["id": "u01", "ord": 1, "title_it": "Piacere!", "title_en": "Nice to meet you", "episode_en": "Arrival",
             "est_minutes": 90, "kind": "unit"],
            ["id": "u02", "ord": 2, "title_it": "Al bar", "title_en": "At the café", "episode_en": "Breakfast",
             "est_minutes": 120, "kind": "unit"],
            ["id": "u99", "ord": 99, "title_it": "Ripasso", "title_en": "Review", "episode_en": "Goodbye",
             "est_minutes": 60, "kind": "final"],
        ])
        try insert(db, "can_dos", [
            ["id": "cd:give-personal-details", "unit_id": "u01", "ord": 1, "text_en": "Give personal details",
             "cefr_scale": "spoken-interaction", "stretch": 0],
            ["id": "cd:order-food-drink", "unit_id": "u02", "ord": 1, "text_en": "Order food and drink",
             "cefr_scale": "spoken-interaction", "stretch": 0],
            ["id": "cd:ask-price-pay", "unit_id": "u02", "ord": 2, "text_en": "Ask the price and pay",
             "cefr_scale": nil, "stretch": 0],
            ["id": "cd:choose-tu-lei", "unit_id": "u02", "ord": 3, "text_en": "Choose tu or Lei",
             "cefr_scale": nil, "stretch": 1],
            ["id": "cd:pass-on-prices", "unit_id": "u02", "ord": 4, "text_en": "Pass on prices",
             "cefr_scale": "mediation", "stretch": 0],
        ])
        try insert(db, "audio", [
            ["id": storyAudio, "file": "000000000001.m4a", "duration_ms": 5_000, "voice": "it-IT-A", "sha256": "s1"],
            ["id": cornettoAudio, "file": "000000000002.m4a", "duration_ms": 800, "voice": "it-IT-B", "sha256": "s2"],
            ["id": checkAudio, "file": "000000000003.m4a", "duration_ms": 2_000, "voice": "it-IT-C", "sha256": "s3"],
        ])
        try fillItems(db)
        try insert(db, "characters", [
            ["id": "ch:narrator", "name": "Narrator", "description_en": "The narrator"],
            ["id": "ch:announcer", "name": "Announcer", "description_en": "Station announcements"],
            ["id": "ch:marco", "name": "Marco", "description_en": "A Canadian in Bologna"],
            ["id": "ch:sara", "name": "Sara", "description_en": "Marco's friend"],
            ["id": "ch:giulia", "name": "Giulia", "description_en": "Runs Bar Aurora"],
        ])
        try insert(db, "countries", [
            ["id": "us", "name_en": "United States", "name_it": "Stati Uniti", "home_phrase_it": "negli Stati Uniti",
             "alt_home_phrases_it": #"["in America"]"#, "nationality_m": "americano", "nationality_f": "americana"],
            ["id": "ca", "name_en": "Canada", "name_it": "Canada", "home_phrase_it": "in Canada",
             "alt_home_phrases_it": "[]", "nationality_m": "canadese", "nationality_f": "canadese"],
        ])
        try insert(db, "lessons", [
            ["id": "u02.l1", "unit_id": "u02", "ord": 1, "title_it": "Un cappuccino, per favore",
             "title_en": "A cappuccino, please", "est_minutes": 25],
            ["id": "u02.l2", "unit_id": "u02", "ord": 2, "title_it": "Al telefono", "title_en": "On the phone",
             "est_minutes": 25],
        ])
        try fillSteps(db)
        try fillTexts(db)
        try insert(db, "grammar_notes", [
            ["id": "u02.l1.note", "unit_id": "u02", "step_id": "u02.l1.step-note", "title_en": "un, una and un'",
             "body": json(exampleNote)],
        ])
        try insert(db, "note_items", [
            ["note_id": "u02.l1.note", "item_id": "g:indefinite-article", "ord": 1],
            ["note_id": "u02.l1.note", "item_id": "g:noun-gender", "ord": 2],
        ])
        try fillExercises(db)
        for assessment in exampleAssessments {
            try insert(db, "assessments", [["id": assessment["id"] as? String, "payload": json(assessment)]])
        }
    }

    private static func fillItems(_ db: Database) throws {
        func item(_ id: String, _ kind: String, _ it: String, gloss: String, unit: String = "u02",
                  lesson: String? = "u02.l1", pos: String? = nil, gender: String? = nil, def: String? = nil,
                  indef: String? = nil, extra: [String: (any DatabaseValueConvertible)?] = [:])
            -> [String: (any DatabaseValueConvertible)?]
        {
            var row: [String: (any DatabaseValueConvertible)?] = [
                "id": id, "kind": kind, "it": it, "gloss_en": gloss, "unit_id": unit, "lesson_id": lesson, "pos": pos,
                "gender": gender, "display_def": def, "display_indef": indef,
            ]
            row.merge(extra) { _, new in new }
            return row
        }
        try insert(db, "items", [
            item("w:ciao", "word", "ciao", gloss: "hi; bye", unit: "u01", lesson: "u01.l1", pos: "interj"),
            item("w:caffe", "word", "caffè", gloss: "coffee; espresso", pos: "noun", gender: "m", def: "il caffè",
                 indef: "un caffè", extra: ["plural": "invariable", "topics": #"["topic:food-drink"]"#]),
            item("w:cappuccino", "word", "cappuccino", gloss: "cappuccino", pos: "noun", gender: "m",
                 def: "il cappuccino", indef: "un cappuccino", extra: ["topics": #"["topic:food-drink"]"#, "flags": 1]),
            item("w:cornetto", "word", "cornetto", gloss: "croissant", pos: "noun", gender: "m", def: "il cornetto",
                 indef: "un cornetto",
                 extra: ["alt_glosses_en": #"["pastry"]"#, "note_en": "In Bologna many people call it a brioche.",
                         "plural": "cornetti", "topics": #"["topic:food-drink"]"#, "audio_id": cornettoAudio]),
            item("w:oggi", "word", "oggi", gloss: "today", pos: "adv"),
            item("w:lei", "word", "Lei", gloss: "you (formal)", pos: "pron"),
            item("c:vorrei", "chunk", "vorrei", gloss: "I'd like"),
            item("c:per-favore", "chunk", "per favore", gloss: "please"),
            item("g:indefinite-article", "grammar", "un, uno, una, un'", gloss: "a, an"),
            item("g:noun-gender", "grammar", "noun gender", gloss: "masculine and feminine nouns"),
            item("g:tu-lei", "grammar", "tu and Lei", gloss: "informal and formal you"),
            item("s:double-consonants", "sound", "consonanti doppie", gloss: "double consonants"),
        ])
        var skills: [[String: (any DatabaseValueConvertible)?]] = []
        for id in ["w:ciao", "w:caffe", "w:cappuccino", "w:cornetto", "w:oggi", "w:lei", "c:vorrei", "c:per-favore"] {
            for skill in ["read", "listen", "recall", "speak"] {
                skills.append(["item_id": id, "skill": skill, "status": id == "w:lei" ? "R" : "P",
                               "scheduled": (id == "w:lei" ? skill == "read" : skill == "recall") ? 1 : 0])
            }
        }
        for id in ["g:indefinite-article", "g:noun-gender"] {
            skills.append(["item_id": id, "skill": "read", "status": "P", "scheduled": 0])
            skills.append(["item_id": id, "skill": "recall", "status": "P", "scheduled": 1])
        }
        skills.append(["item_id": "g:tu-lei", "skill": "read", "status": "R", "scheduled": 1])
        skills.append(["item_id": "s:double-consonants", "skill": "listen", "status": "P", "scheduled": 1])
        try insert(db, "item_skills", skills)
        try insert(db, "item_requires", [["item_id": "g:indefinite-article", "requires_id": "g:noun-gender"]])
        try insert(db, "forms", [
            ["form": "caffè", "item_id": "w:caffe", "morph": "NOUN-M:s"],
            ["form": "cornetto", "item_id": "w:cornetto", "morph": "NOUN-M:s"],
            ["form": "cornetti", "item_id": "w:cornetto", "morph": "NOUN-M:p"],
            ["form": "cappuccino", "item_id": "w:cappuccino", "morph": "NOUN-M:s"],
            ["form": "oggi", "item_id": "w:oggi", "morph": ""],
            ["form": "vorrei", "item_id": "c:vorrei", "morph": ""],
        ])
        // One pair with audio objects, one written as bare words (accepted too).
        try insert(db, "sounds", [
            ["item_id": "s:double-consonants",
             "pairs": #"[[{"it": "eco", "audioId": null}, {"it": "ecco", "audioId": "a:000000000002"}], "#
                + #"["pena", "penna"]]"#],
        ])
    }

    private static func fillSteps(_ db: Database) throws {
        try insert(db, "steps", [
            ["id": "u01.step-writing", "unit_id": "u01", "lesson_id": nil, "ord": 1, "kind": "writing",
             "title_en": "Writing", "payload": json(["kind": "writing", "exerciseId": "u01.task.write"]),
             "est_seconds": 300, "strand": "output"],
        ])
        for payload in exampleSteps {
            guard let kind = payload["kind"] as? String, let place = stepIDs[kind] else {
                fatalError("no step ID for \(payload)")
            }
            try insert(db, "steps", [
                ["id": place.id, "unit_id": "u02", "lesson_id": place.lesson, "ord": place.ord, "kind": kind,
                 "title_en": kind == "opener" ? nil : kind.capitalized, "payload": json(payload),
                 "est_seconds": 60 * place.ord, "strand": place.strand, "draft": kind == "reading" ? 1 : 0],
            ])
        }
        try insert(db, "step_introduces", [
            ["step_id": "u02.l1.step-preview", "item_id": "w:caffe", "skill": "read"],
            ["step_id": "u02.l1.step-preview", "item_id": "w:caffe", "skill": "listen"],
            ["step_id": "u02.l1.step-preview", "item_id": "c:vorrei", "skill": "recall"],
            ["step_id": "u02.l1.step-preview", "item_id": "c:vorrei", "skill": "read"],
            ["step_id": "u02.l1.step-note", "item_id": "g:indefinite-article", "skill": "read"],
            ["step_id": "u02.l1.step-note", "item_id": "g:noun-gender", "skill": "read"],
            ["step_id": "u02.l1.step-sounds", "item_id": "s:double-consonants", "skill": "listen"],
        ])
    }

    /// The story's lines: (speaker, addressee, register, Italian, English, tokens as (surface, trailing, kind, item)).
    typealias TokenRow = (surface: String, trailing: String, kind: String, item: String?)
    static let storyLines: [(speaker: String, to: String?, register: String?, it: String, en: String,
                             tokens: [TokenRow])] = [
        ("ch:narrator", nil, nil, "Marco è in un bar.", "Marco is in a café.", [
            ("Marco", " ", "name", nil), ("è", " ", "word", nil), ("in", " ", "word", nil), ("un", " ", "word", nil),
            ("bar", "", "word", nil), (".", "", "punct", nil),
        ]),
        ("ch:giulia", "ch:marco", "lei", "Buongiorno! Cosa prende?", "Good morning! What will you have?", [
            ("Buongiorno", "", "word", nil), ("!", " ", "punct", nil), ("Cosa", " ", "word", nil),
            ("prende", "", "word", nil), ("?", "", "punct", nil),
        ]),
        ("ch:marco", "ch:giulia", "lei", "«Vorrei un cappuccino, per favore.»",
         "I'd like a cappuccino, please.", [
            ("Vorrei", " ", "word", "c:vorrei"), ("un", " ", "word", "w:cappuccino"),
            ("cappuccino", "", "word", "w:cappuccino"), (",", " ", "punct", nil), ("per", " ", "word", "c:per-favore"),
            ("favore", "", "word", "c:per-favore"), (".»", "", "punct", nil),
         ]),
    ]

    private static func fillTexts(_ db: Database) throws {
        try insert(db, "texts", [
            ["id": "u02.l1.story", "unit_id": "u02", "kind": "story", "title_it": "Bar Aurora",
             "title_en": "Bar Aurora", "audio_id": storyAudio, "duration_ms": 5_000],
            ["id": "u02.l2.phone", "unit_id": "u02", "kind": "phone", "title_it": nil, "title_en": "A phone call"],
            ["id": "u02.l2.menu", "unit_id": "u02", "kind": "real_world", "layout": json(exampleLayout)],
            ["id": "u02.task.menu", "unit_id": "u02", "kind": "real_world", "layout": json(exampleLayout)],
            ["id": "u02.check.01.audio", "unit_id": "u02", "kind": "dialogue", "audio_id": checkAudio,
             "duration_ms": 2_000],
        ])
        var clock = 0
        for (n, line) in storyLines.enumerated() {
            let number = n + 1
            let start = clock
            var tokenRows: [[String: (any DatabaseValueConvertible)?]] = []
            for (i, t) in line.tokens.enumerated() {
                let timed = t.kind != "punct"
                tokenRows.append([
                    "text_id": "u02.l1.story", "line_ord": number, "ord": i + 1, "surface": t.surface,
                    "trailing": t.trailing, "kind": t.kind, "item_id": t.item,
                    "gloss_en": t.surface == "prende" ? "will you have" : nil, "flags": t.item == "c:vorrei" ? 1 : 0,
                    "start_ms": timed ? clock : nil, "end_ms": timed ? clock + 300 : nil,
                ])
                if timed { clock += 350 }
            }
            try insert(db, "text_lines", [
                ["text_id": "u02.l1.story", "ord": number, "speaker_id": line.speaker, "addressee_id": line.to,
                 "register": line.register, "it": line.it, "en": line.en, "start_ms": start, "end_ms": clock],
            ])
            try insert(db, "tokens", tokenRows)
            clock += 300
        }
        try insert(db, "text_lines", [
            ["text_id": "u02.l2.phone", "ord": 1, "speaker_id": "ch:sara", "it": "Pronto?", "en": "Hello?"],
            ["text_id": "u02.check.01.audio", "ord": 1, "speaker_id": "ch:giulia", "it": "Prego?",
             "en": "Yes, please?", "start_ms": 0, "end_ms": 600],
        ])
        try insert(db, "tokens", [
            ["text_id": "u02.l2.phone", "line_ord": 1, "ord": 1, "surface": "Pronto", "trailing": "", "kind": "word"],
            ["text_id": "u02.l2.phone", "line_ord": 1, "ord": 2, "surface": "?", "trailing": "", "kind": "punct"],
            ["text_id": "u02.check.01.audio", "line_ord": 1, "ord": 1, "surface": "Prego", "trailing": "",
             "kind": "word", "start_ms": 0, "end_ms": 500],
            ["text_id": "u02.check.01.audio", "line_ord": 1, "ord": 2, "surface": "?", "trailing": "", "kind": "punct"],
        ])
        try insert(db, "text_requires", [
            ["text_id": "u02.l1.story", "item_id": "c:vorrei", "skill": "read"],
            ["text_id": "u02.l1.story", "item_id": "w:cappuccino", "skill": "read"],
            ["text_id": "u02.l2.phone", "item_id": "w:caffe", "skill": "listen"],
        ])
    }

    /// Every example exercise plus the copies, as payload dictionaries.
    static var allExercisePayloads: [[String: Any]] {
        let byID = Dictionary(uniqueKeysWithValues: exampleExercises.compactMap { e in
            (e["id"] as? String).map { ($0, e) }
        })
        var out = exampleExercises
        for copy in copies {
            guard var payload = byID[copy.from] else { fatalError("no example \(copy.from)") }
            payload["id"] = copy.id
            payload["stepId"] = copy.step
            if let role = copy.role { payload["role"] = role }
            if copy.id.hasSuffix(".b1.match"), let targets = payload["targets"] as? [Any] {
                payload["targets"] = Array(targets.reversed())  // authored order ≠ sorted order
            }
            out.append(payload)
        }
        return out
    }

    private static func fillExercises(_ db: Database) throws {
        for payload in allExercisePayloads {
            guard let id = payload["id"] as? String else { fatalError("exercise without id") }
            let source = payload["source"] as? [String: Any]
            let sourceRef = source.flatMap { s in
                (s["textId"] as? String).map { t in (s["line"] as? Int).map { "\(t)#\($0)" } ?? t }
            }
            try insert(db, "exercises", [
                ["id": id, "format": payload["format"] as? String, "unit_id": payload["unitId"] as? String,
                 "step_id": payload["stepId"] as? String, "role": payload["role"] as? String, "payload": json(payload),
                 "score": payload["score"] as? Int ?? 1, "est_seconds": 30, "source_ref": sourceRef],
            ])
            for target in payload["targets"] as? [[String: Any]] ?? [] {
                try insert(db, "exercise_targets", [
                    ["exercise_id": id, "item_id": target["itemId"] as? String, "skill": target["skill"] as? String],
                ])
            }
            for tag in payload["tags"] as? [String] ?? [] {
                try insert(db, "exercise_tags", [["exercise_id": id, "tag": tag]])
            }
        }
        try insert(db, "exercise_requires", [
            ["exercise_id": "u02.l1.ex01", "item_id": "c:vorrei", "skill": "read"],
            ["exercise_id": "u02.l1.ex01", "item_id": "w:cappuccino", "skill": "read"],
            ["exercise_id": "u02.l1.ex01", "item_id": "g:indefinite-article", "skill": "recall"],
            ["exercise_id": "u02.l1.ex04", "item_id": "w:cornetto", "skill": "recall"],
        ])
    }
}
