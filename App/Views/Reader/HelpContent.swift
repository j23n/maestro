import Foundation
import ItalianCore
import LexiconKit
import PackKit

/// A tapped token, or the unit it belongs to, in a text.
struct TokenSelection: Hashable {
    let sentenceIndex: Int
    let tokenIndex: Int
}

/// Everything tap-for-help shows (HANDOFF.md 3.1), worked out from the pack's pre-linked analysis
/// and the dictionary.
struct HelpContent {
    let surface: String
    let gloss: String?
    let headword: String?
    let analysis: String?          // "condizionale passato · noi"
    let splits: [String]           // "dai = da + i"
    let note: String?
    let grammarIDs: [String]
    let sentenceTranslation: String
    let lemmaID: String?
    let isVerb: Bool
    let formTag: String?
    let items: [RememberItem]
    /// Token ranges within the sentence, for the card snapshot and the selection highlight.
    let tokenIndices: [Int]

    init(text: ReadingText, sentence: Sentence, tokenIndex: Int, content: ContentDatabase?) {
        let token = sentence.tokens[tokenIndex]
        let unit = sentence.unit(containing: tokenIndex)
        let indices = unit?.tokens.sorted() ?? [tokenIndex]
        tokenIndices = indices
        let ranges = indices.compactMap { sentence.tokens.indices.contains($0) ? sentence.tokens[$0].r : nil }

        let surface = unit?.surface ?? token.t
        self.surface = surface
        let lemmaID = unit?.lemmaID ?? token.lemmaID ?? token.parts?.first(where: { $0.lemmaID != nil })?.lemmaID
        self.lemmaID = lemmaID
        let senseID = unit?.senseID ?? token.senseID
        let formTag = unit?.form ?? token.form
        self.formTag = formTag
        let lemma = lemmaID.flatMap { content?.lemma($0) }
        let headword = lemma?.headword ?? lemmaID.map(LemmaID.headword(of:))
        self.headword = headword
        let pos = lemma?.pos ?? lemmaID.map(LemmaID.pos(of:)) ?? ""
        let isVerb = pos == "v" || token.pos == "VERB" || token.pos == "AUX"
        self.isVerb = isVerb

        let senseGloss = senseID.flatMap { content?.sense($0)?.gloss }
        gloss = unit?.gloss ?? token.gloss ?? senseGloss ?? lemma?.firstGloss

        if let tag = formTag.flatMap(FormTag.init) {
            analysis = tag.label
        } else if let gn = token.genderNumber {
            analysis = "\(PartOfSpeech.label(pos)), \(gn.label)"
        } else if !pos.isEmpty {
            analysis = PartOfSpeech.label(pos)
        } else {
            analysis = nil
        }

        if let parts = token.parts, !parts.isEmpty, unit == nil {
            splits = ["\(token.t) = " + parts.map(\.t).joined(separator: " + ")]
        } else {
            splits = []
        }

        let grammarIDs = unit?.grammar ?? token.grammar ?? []
        self.grammarIDs = grammarIDs
        note = unit?.note ?? token.note
        sentenceTranslation = sentence.translation

        // Remember rows: Word, Verb form, Grammar.
        var items: [RememberItem] = []
        func snapshot(_ item: RememberItem) -> RememberItem {
            item.inSentence(textID: text.id, sentenceID: sentence.id, text: sentence.text,
                            translation: sentence.translation, ranges: ranges)
        }
        if let lemmaID {
            let sense = senseID ?? content?.entry(lemmaID)?.senses.first(where: { !$0.retired })?.id
            if let sense {
                items.append(snapshot(.word(lemmaID: lemmaID, senseID: sense, surface: headword ?? surface)))
            }
            if let formTag, let tag = FormTag(formTag), isVerb, !(tag.mood == .inf && tag.tense == .pres) {
                items.append(snapshot(.verbForm(lemmaID: lemmaID, formTag: formTag, surface: surface)))
            }
        } else if let parts = token.parts {
            for part in parts {
                guard let lid = part.lemmaID else { continue }
                let sense = part.senseID ?? content?.entry(lid)?.senses.first(where: { !$0.retired })?.id
                if let sense {
                    items.append(snapshot(.word(lemmaID: lid, senseID: sense, surface: LemmaID.headword(of: lid))))
                }
            }
        }
        for g in grammarIDs {
            items.append(snapshot(.grammar(g, surface: surface)))
        }
        self.items = items
    }
}
