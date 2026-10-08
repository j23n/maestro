import Foundation

/// One entry of Settings → Acknowledgements (task M3.8), from `docs/13` § Licences: what the app ships (fonts, the
/// storage library, synthetic voices) and the build-time data the course was made with.
struct Acknowledgement: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    /// What it is and what Italiano uses it for.
    let credit: String
    /// "SIL Open Font License 1.1".
    let licence: String
    let url: String?
    /// A licence text bundled under `Resources/Licenses` (without `.txt`).
    var licenceFile: String?
    /// A licence text carried here (short notices whose terms ask for the text, such as MIT).
    var licenceText: String?
    /// The first words of its row in `docs/13` § Licences (the completeness test matches them).
    let docsRow: String
}

enum Acknowledgements {
    static let intro =
        "Italiano is built with the work of these people and projects. Thank you. The course itself (stories, "
        + "notes and exercises) is written for Italiano."

    static let all: [Acknowledgement] = [
        Acknowledgement(
            id: "literata", name: "Literata",
            credit: "The typeface for Italian text. Copyright 2017 The Literata Project Authors.",
            licence: "SIL Open Font License 1.1", url: "https://github.com/googlefonts/literata",
            licenceFile: "LICENSE-Literata-OFL", docsRow: "Literata, Instrument Sans"),
        Acknowledgement(
            id: "instrument-sans", name: "Instrument Sans",
            credit: "The typeface for everything else. Copyright 2022 The Instrument Sans Project Authors.",
            licence: "SIL Open Font License 1.1", url: "https://github.com/Instrument/instrument-sans",
            licenceFile: "LICENSE-InstrumentSans-OFL", docsRow: "Literata, Instrument Sans"),
        Acknowledgement(
            id: "voices", name: "Synthetic voices",
            credit: "The course audio is spoken by synthetic voices, made with Microsoft Azure neural "
                + "text-to-speech. No human voice recordings are used.",
            licence: "Generated on a paid tier that allows commercial use", url: nil,
            docsRow: "Azure neural TTS output"),
        Acknowledgement(
            id: "grdb", name: "GRDB.swift",
            credit: "Keeps your progress in a database on this device. Copyright (C) 2015-2025 Gwendal Roué.",
            licence: "MIT License", url: "https://github.com/groue/GRDB.swift", licenceText: mitGRDB,
            docsRow: "GRDB.swift"),
        Acknowledgement(
            id: "morph-it", name: "Morph-it!",
            credit: "A morphological lexicon of Italian by Eros Zanchetta and Marco Baroni. It checked the course's "
                + "words while the course was being built; it isn't part of the app.",
            licence: "Creative Commons Attribution-ShareAlike 2.0",
            url: "https://docs.sslmit.unibo.it/doku.php?id=resources:morph-it",
            docsRow: "Morph-it!"),
        Acknowledgement(
            id: "frequency-words", name: "FrequencyWords",
            credit: "Word frequencies from OpenSubtitles 2018, compiled by Hermit Dave. They helped choose which "
                + "words to teach first; they aren't part of the app.",
            licence: "Creative Commons Attribution-ShareAlike 4.0", url: "https://github.com/hermitdave/FrequencyWords",
            docsRow: "FrequencyWords"),
        Acknowledgement(
            id: "fsrs", name: "FSRS",
            credit: "Reviews are scheduled with the FSRS-6 algorithm of the Open Spaced Repetition project; its "
                + "reference implementation, py-fsrs, checked ours while it was being built.",
            licence: "MIT License (py-fsrs)", url: "https://github.com/open-spaced-repetition/py-fsrs",
            docsRow: "py-fsrs"),
    ]

    /// Rows of `docs/13` § Licences that aren't credited, and why (the completeness test reads both lists).
    static let notCredited: [String: String] = [
        "Wiktionary via kaikki.org": "an optional build-time cross-check; nothing from it is used",
        "Tatoeba sentences": "not used in the MVP",
        "**Forbidden**": "never used",
        "Exam papers and syllabi": "never used in content or the app",
    ]

    /// The full licence text: the bundled file or the text carried here.
    static func licenceText(for entry: Acknowledgement, in directories: [URL]) -> String? {
        if let text = entry.licenceText { return text }
        guard let name = entry.licenceFile else { return nil }
        for folder in directories {
            let url = folder.appendingPathComponent(name).appendingPathExtension("txt")
            if let data = FileManager.default.contents(atPath: url.path) {
                return String(decoding: data, as: UTF8.self)
            }
        }
        return nil
    }

    /// Where the app bundle keeps the licence files: the resources folder itself (synchronized folders copy files
    /// flat) or a `Licenses` folder inside it.
    static func bundleDirectories(_ bundle: Bundle = .main) -> [URL] {
        guard let resources = bundle.resourceURL else { return [] }
        return [resources, resources.appendingPathComponent("Licenses")]
    }

    static let mitGRDB = """
        Copyright (C) 2015-2025 Gwendal Roué

        Permission is hereby granted, free of charge, to any person obtaining a copy of this software and \
        associated documentation files (the "Software"), to deal in the Software without restriction, including \
        without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell \
        copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the \
        following conditions:

        The above copyright notice and this permission notice shall be included in all copies or substantial \
        portions of the Software.

        THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT \
        LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO \
        EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER \
        IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR \
        THE USE OR OTHER DEALINGS IN THE SOFTWARE.
        """
}
