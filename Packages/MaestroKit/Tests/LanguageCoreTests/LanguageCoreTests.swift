import Testing
@testable import LanguageCore

@Suite struct FormTagTests {
    @Test func parsesFiniteAndNonFinite() throws {
        let tag = try #require(FormTag("cond.pass.1p"))
        #expect(tag.mood == .cond && tag.tense == .pass && tag.person == .p1 && tag.auxiliary == nil)
        #expect(tag.description == "cond.pass.1p")
        #expect(FormTag("part.pass")?.person == nil)
        #expect(FormTag("ind.pp.3s+e")?.auxiliary == .essere)
        #expect(FormTag("ind.pp.3s+e")?.description == "ind.pp.3s+e")
    }

    @Test func rejectsBadTags() {
        #expect(FormTag("ind.impf") == nil)        // finite mood needs a person
        #expect(FormTag("part.pass.1s") == nil)    // non-finite mood takes none
        #expect(FormTag("ind.xyz.1s") == nil)
        #expect(FormTag("ind.pp.3s+x") == nil)
        #expect(FormTag("") == nil)
    }

    @Test func labelsComeFromTags() {
        #expect(FormTag("cond.pass.1p")?.label == "condizionale passato · noi")
        #expect(FormTag("ind.impf.1p")?.label == "indicativo imperfetto · noi")
        #expect(FormTag("imp.neg.2s")?.tenseLabel == "imperativo negativo")
        #expect(FormTag("part.pass")?.label == "participio passato")
    }
}

@Suite struct TextTests {
    @Test func utf16RangesSliceNFCText() {
        let s = "L'anno in cui compii sedici anni, però"
        #expect(s.substring(UTF16Range(start: 0, length: 2)) == "L'")
        #expect(s.substring(UTF16Range(start: 34, length: 4)) == "però")
        #expect(s.substring(UTF16Range(start: 36, length: 10)) == nil)
    }

    @Test func emojiCountsAsTwoUnits() {
        let s = "Ciao 👋 Marta"
        #expect(s.utf16Length == 13)
        #expect(s.substring(UTF16Range(start: 8, length: 5)) == "Marta")
    }

    @Test func rangeListRoundTrips() {
        let ranges = [UTF16Range(start: 14, length: 6), UTF16Range(start: 27, length: 3)]
        #expect(UTF16Range.string(from: ranges) == "14:6,27:3")
        #expect(UTF16Range.list(from: "14:6,27:3") == ranges)
    }

    @Test func normalizer() {
        #expect(Normalizer.query("  Dall’Italia  ") == "dall'italia")
        #expect(Normalizer.splitElision("dall'italia") == ["dall'", "italia"])
        #expect(Normalizer.fold("Perché") == "perche")
        #expect(Normalizer.fold("andò") == "ando")
    }
}

@Suite struct ItemKeyTests {
    @Test func keysPerKind() {
        #expect(ItemKey.word(lemmaID: "it:andare:v", senseID: "it:andare:v#k3fq") == "word|it:andare:v|it:andare:v#k3fq")
        #expect(ItemKey.verbForm(lemmaID: "it:andare:v", formTag: "cond.pass.1p") == "verbForm|it:andare:v|cond.pass.1p")
        #expect(ItemKey.grammar("future-in-the-past") == "grammar|future-in-the-past")
        #expect(ItemKey.kind(of: "verbForm|it:andare:v|cond.pass.1p") == .verbForm)
    }

    @Test func resolvesThroughRedirects() {
        let redirects = ["it:andare:v#old1": "it:andare:v#k3fq"]
        let resolve: (String) -> String? = { redirects[$0] ?? $0 }
        #expect(ItemKey.resolved("word|it:andare:v|it:andare:v#old1", resolve: resolve) == "word|it:andare:v|it:andare:v#k3fq")
        #expect(ItemKey.resolved("word|it:x:n|it:x:n#aaaa", resolve: { _ in nil }) == nil)
        #expect(ItemKey.resolved("nonsense", resolve: resolve) == nil)
    }

    @Test func lemmaIDParts() {
        #expect(LemmaID.headword(of: "it:essere_d'accordo:phr") == "essere d'accordo")
        #expect(LemmaID.pos(of: "it:pesca:n:2") == "n")
        #expect(LemmaID.of(senseID: "it:andare:v#k3fq") == "it:andare:v")
    }
}

@Suite struct LanguageTests {
    @Test func readsTheLanguageOfAnID() {
        #expect(Language.of(id: "it:andare:v") == .it)
        #expect(Language.of(id: "it:andare:v#k3fq") == .it)
        #expect(Language.of(id: "de:Haus:n") == .de)
        #expect(Language.of(id: "de:gehen:v#ab12") == .de)
        #expect(Language.of(id: "de:dativ") == .de)
        // No prefix means Italian: grammar slugs and text IDs shipped before German.
        #expect(Language.of(id: "future-in-the-past") == .it)
        #expect(Language.of(id: "racconti-brevi-03") == .it)
        #expect(Language.of(id: "") == .it)
        // A language this build doesn't know.
        #expect(Language.of(id: "fr:maison:n") == nil)
    }

    @Test func readsTheLanguageOfAnItemKey() {
        #expect(Language.of(itemKey: ItemKey.word(lemmaID: "it:casa:n", senseID: "it:casa:n#aaaa")) == .it)
        #expect(Language.of(itemKey: ItemKey.verbForm(lemmaID: "de:gehen:v", formTag: "ind.prat.1s")) == .de)
        #expect(Language.of(itemKey: ItemKey.grammar("de:dativ")) == .de)
        #expect(Language.of(itemKey: ItemKey.grammar("articles")) == .it)
        #expect(Language.of(itemKey: "nonsense") == .it)
        #expect(Language.of(itemKey: ItemKey.word(lemmaID: "fr:maison:n", senseID: "fr:maison:n#aaaa")) == nil)
    }

    @Test func namesAndLocales() {
        #expect(Language.it.bcp47 == "it-IT" && Language.it.localeIdentifier == "it_IT")
        #expect(Language.de.bcp47 == "de-DE" && Language.de.name == "German")
        #expect(Language.de.accentKeys.contains("ß"))
        #expect(Language(rawValue: "de") == .de && Language(rawValue: "fr") == nil)
    }
}
