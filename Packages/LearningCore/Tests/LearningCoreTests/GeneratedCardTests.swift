import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Review session builder (generated cards) and docs/06 § 1.
@Suite struct GeneratedCardTests {
    static func item(_ id: ItemID, _ it: String, gloss: String, pos: String? = nil, gender: Gender? = nil,
                     def: String? = nil, indef: String? = nil, recallAnswer: String? = nil,
                     topics: [String] = []) -> ContentIndex.Item
    {
        ContentIndex.Item(id: id, it: it, gloss: gloss, pos: pos, gender: gender, displayDef: def, displayIndef: indef,
                          recallAnswer: recallAnswer, topics: topics, unitId: "u02", skills: TestCourse.allP)
    }

    func recall(_ item: ContentIndex.Item) throws -> GeneratedRecallCard {
        try #require(GeneratedCards.recall(for: item))
    }

    @Test func masculineNoun() throws {
        let card = try recall(Self.item("w:cornetto", "cornetto", gloss: "croissant", pos: "noun", gender: .m,
                                        def: "il cornetto", indef: "un cornetto"))
        #expect(card.exerciseId == "gen:recall:w:cornetto")
        #expect(card.promptEn == "croissant")
        #expect(card.answer == "{il|un} [cornetto]")
        #expect(card.near == [
            GeneratedNearAnswer(answer: "cornetto", outcome: .correctWithNote,
                                hint: "Say it with its article: il cornetto"),
            GeneratedNearAnswer(answer: "{la cornetto|una cornetto}", outcome: .almost,
                                hint: "cornetto is masculine: il cornetto"),
        ])
    }

    @Test func feminineNounAndTheGlossUpToTheFirstSemicolon() throws {
        let card = try recall(Self.item("w:spremuta", "spremuta", gloss: "fresh-squeezed juice; juice", pos: "noun",
                                        gender: .f, def: "la spremuta", indef: "una spremuta"))
        #expect(card.promptEn == "fresh-squeezed juice")
        #expect(card.answer == "{la|una} [spremuta]")
        #expect(card.near[1] == GeneratedNearAnswer(
            answer: "{il spremuta|lo spremuta|un spremuta|uno spremuta}", outcome: .almost,
            hint: "spremuta is feminine: la spremuta"))
    }

    @Test func elidedArticlesAndTheGenderMark() throws {
        let card = try recall(Self.item("w:acqua", "acqua", gloss: "water", pos: "noun", gender: .f,
                                        def: "l'acqua (f)", indef: "un'acqua"))
        // Model answer: the display form without its gender mark.
        #expect(card.answer == "{[l'acqua]|[un'acqua]}")
        #expect(card.near[0] == GeneratedNearAnswer(answer: "acqua", outcome: .correctWithNote,
                                                    hint: "Say it with its article: l'acqua"))
        #expect(card.near[1].answer == "{il acqua|lo acqua|un acqua|uno acqua}")
        #expect(card.near[1].hint == "acqua is feminine: l'acqua")

        let amico = try recall(Self.item("w:albero", "albero", gloss: "tree", pos: "noun", gender: .m,
                                         def: "l'albero", indef: "un albero"))
        #expect(amico.answer == "{[l'albero]|un [albero]}")
        // l' fits both genders, so it is never a wrong article; un' is.
        #expect(amico.near[1].answer == "{la albero|una albero|un'albero}")
    }

    @Test func loNouns() throws {
        let card = try recall(Self.item("w:zaino", "zaino", gloss: "backpack", pos: "noun", gender: .m,
                                        def: "lo zaino", indef: "uno zaino"))
        #expect(card.answer == "{lo|uno} [zaino]")
        #expect(card.near[1].answer == "{la zaino|una zaino}")
    }

    @Test func recallAnswerOverridesTheDefault() throws {
        let card = try recall(Self.item("w:amico", "amico", gloss: "friend", pos: "noun", gender: .mf,
                                        def: "l'amico / l'amica", recallAnswer: "{l'amico|l'amica|un amico|un'amica}"))
        #expect(card.answer == "{l'amico|l'amica|un amico|un'amica}")
        #expect(card.near.isEmpty)
    }

    @Test func peopleNounsWithBothFormsAcceptBoth() throws {
        let card = try recall(Self.item("w:ragazzo", "ragazzo", gloss: "boy; girl", pos: "noun", gender: .mf,
                                        def: "il ragazzo / la ragazza", indef: "un ragazzo / una ragazza"))
        #expect(card.answer == "{il [ragazzo]|la [ragazza]|un [ragazzo]|una [ragazza]}")
        #expect(card.near == [GeneratedNearAnswer(answer: "{ragazzo|ragazza}", outcome: .correctWithNote,
                                                  hint: "Say it with its article: il ragazzo")])
    }

    @Test func otherWordsAreTheLemmaAsFocus() throws {
        #expect(try recall(Self.item("w:oggi", "oggi", gloss: "today", pos: "adv")).answer == "[oggi]")
        #expect(try recall(Self.item("w:buono", "buono", gloss: "good; tasty", pos: "adj", gender: .mf)).answer
                == "[buono]")
    }

    @Test func chunksDropTrailingPunctuation() throws {
        func chunk(_ it: String) -> ContentIndex.Item { Self.item("c:x", it, gloss: "x") }
        #expect(try recall(chunk("quant'è?")).answer == "quant'è")
        #expect(try recall(chunk("senta…")).answer == "senta")
        #expect(try recall(chunk("ti piace…?")).answer == "ti piace")
        #expect(try recall(chunk("Le piace…?")).answer == "Le piace")
        #expect(try recall(chunk("come si dice (in italiano)?")).answer == #"come si dice \(in italiano)"#)
        #expect(GeneratedCards.recall(for: chunk("tu/Lei")) == nil)  // lint requires recall_answer
        var withAnswer = chunk("piacere/piacere mio")
        withAnswer.recallAnswer = "piacere( mio)"
        #expect(try recall(withAnswer).answer == "piacere( mio)")
    }

    @Test func grammarPointsAndSoundsGetNoRecall() {
        #expect(GeneratedCards.recall(for: TestCourse.standard.item(TestCourse.grammarP(0))!) == nil)
        #expect(GeneratedCards.recall(for: TestCourse.standard.item(TestCourse.sound(0))!) == nil)
    }

    // MARK: Read

    static let pool: [ContentIndex.Item] = [
        item("w:caffe", "caffè", gloss: "coffee; espresso", pos: "noun", def: "il caffè", topics: ["topic:food"]),
        item("w:cornetto", "cornetto", gloss: "croissant", pos: "noun", def: "il cornetto", topics: ["topic:food"]),
        item("w:spremuta", "spremuta", gloss: "juice", pos: "noun", def: "la spremuta", topics: ["topic:food"]),
        item("w:latte", "latte", gloss: "milk", pos: "noun", def: "il latte", topics: ["topic:food"]),
        item("w:treno", "treno", gloss: "train", pos: "noun", def: "il treno", topics: ["topic:travel"]),
        item("w:casa", "casa", gloss: "house", pos: "noun", def: "la casa", topics: ["topic:home"]),
        item("w:oggi", "oggi", gloss: "today", pos: "adv"),
        item("w:ecco", "ecco", gloss: "here is", pos: "adv"),
        item("w:espresso", "espresso", gloss: "coffee", pos: "noun", def: "l'espresso", topics: ["topic:food"]),
    ]

    @Test func readCardsDrawSamePOSDistractorsPreferringTheTopic() throws {
        let caffe = Self.pool[0]
        for seed in 0..<50 {
            var rng = SplitMix64(seedString: "session-\(seed)")
            let card = try #require(GeneratedCards.read(for: caffe, pool: Self.pool, rng: &rng))
            #expect(card.exerciseId == "gen:read:w:caffe")
            #expect(card.promptIt == "il caffè")
            #expect(card.options.count == 4)
            #expect(card.options[card.answer] == "coffee")
            let distractors = Set(card.options).subtracting(["coffee"])
            // Same topic and POS first: croissant, juice, milk (never the duplicate gloss "coffee").
            #expect(distractors == ["croissant", "juice", "milk"])
        }
        // The right answer's position varies between sessions.
        let positions = Set((0..<40).compactMap { seed -> Int? in
            var rng = SplitMix64(seedString: "s\(seed)")
            return GeneratedCards.read(for: caffe, pool: Self.pool, rng: &rng)?.answer
        })
        #expect(positions.count == 4)
    }

    @Test func readCardsTopUpFromOtherWordsAndNeedOneDistractor() throws {
        var rng = SplitMix64(seedString: "x")
        let oggi = Self.pool[6]
        let card = try #require(GeneratedCards.read(for: oggi, pool: Self.pool, rng: &rng))
        #expect(card.options.count == 4)
        #expect(card.options.contains("here is"))  // the only other adverb comes first
        #expect(GeneratedCards.read(for: oggi, pool: [oggi], rng: &rng) == nil)
        #expect(GeneratedCards.read(for: TestCourse.standard.item(TestCourse.grammarR(0))!, pool: Self.pool,
                                    rng: &rng) == nil)
    }

    @Test func sameSessionSameCard() {
        var a = SplitMix64(seedString: "session")
        var b = SplitMix64(seedString: "session")
        #expect(GeneratedCards.read(for: Self.pool[1], pool: Self.pool, rng: &a)
                == GeneratedCards.read(for: Self.pool[1], pool: Self.pool, rng: &b))
    }

    // MARK: Listen

    @Test func listenCardsPlayOneWordOfAPair() throws {
        let sound = ContentIndex.Sound(itemId: "s:double-consonants", pairs: [
            [.init(it: "pena"), .init(it: "penna")], [.init(it: "caro"), .init(it: "carro")], [.init(it: "solo")],
        ])
        var seen = Set<String>()
        for seed in 0..<40 {
            var rng = SplitMix64(seedString: "l\(seed)")
            let card = try #require(GeneratedCards.listen(for: sound, rng: &rng))
            #expect(card.exerciseId == "gen:listen:s:double-consonants")
            #expect(card.pair.count == 2)
            seen.insert(card.pair[card.play].it)
        }
        #expect(seen == ["pena", "penna", "caro", "carro"])
        var rng = SplitMix64(seed: 1)
        #expect(GeneratedCards.listen(for: .init(itemId: "s:x", pairs: [[.init(it: "a")]]), rng: &rng) == nil)
    }
}

/// docs/05 § Review session builder, step 2 (`CardSelector`).
@Suite struct CardSelectorTests {
    typealias C = TestCourse
    let content = TestCourse.standard

    func device() -> TestDevice {
        let d = TestDevice()
        d.run(C.step(0, "preview"))
        d.run(C.step(0, "story"))
        d.run(C.step(0, "note"))
        return d
    }

    @Test func preferredFormats() {
        #expect(CardSelector.preferredFormats(for: .recall) == [.recall, .cloze, .sentenceBuilding, .dictation])
        #expect(CardSelector.preferredFormats(for: .read) == [.choice, .match])
        #expect(CardSelector.preferredFormats(for: .listen) == [.soundPair, .choice])
    }

    @Test func candidatesAreEligibleLearnExercisesNotShownForTwoDays() {
        let d = device()
        let selector = CardSelector(content: content, state: d.state)
        let pair = ItemSkillPair(C.grammarP(0), .recall)
        // ex01 and ex12 target it; both are eligible; neither was shown yet (the practice step wasn't run).
        #expect(selector.candidates(for: pair, now: d.now).map(\.id).sorted() == [C.ex(0, 1), C.ex(0, 12)])
        d.answer(C.ex(0, 1), .correct, context: .review, session: "r")
        let later = CardSelector(content: content, state: d.state)
        #expect(later.candidates(for: pair, now: d.now + day).map(\.id) == [C.ex(0, 12)])
        #expect(later.candidates(for: pair, now: d.now + 2 * day).count == 2)
        #expect(later.candidates(for: pair, now: d.now + day, allowRecent: true).count == 2)
        // Check and placement exercises are never review cards.
        #expect(!selector.candidates(for: ItemSkillPair(C.noun(0, 3), .recall), now: d.now)
            .contains { $0.role != .learn })
    }

    @Test func ineligibleExercisesAreNeverCandidates() {
        let d = TestDevice()
        let adverb = ItemSkillPair(C.adverb(0), .recall)
        d.record(d.factory.introduced([adverb, ItemSkillPair(C.grammarR(0), .read)], via: .debug))
        let selector = CardSelector(content: content, state: d.state)
        // The sentence-building also requires noun 1 for recall, which isn't introduced; the preview's recall is fine.
        #expect(selector.candidates(for: adverb, now: d.now).map(\.id)
                == ["u00.l1.step-preview.b1.w-u00-a1"])
        // The R point's only exercise also needs the chunk: no candidate, and grammar points get no generated card.
        let grammar = ItemSkillPair(C.grammarR(0), .read)
        #expect(selector.candidates(for: grammar, now: d.now).isEmpty)
        #expect(!selector.hasCard(for: grammar, now: d.now))
        // Once the eligible exercise was shown, the adverb's card is generated.
        d.answer("u00.l1.step-preview.b1.w-u00-a1", .correct)
        var rng = SplitMix64(seed: 1)
        let card = CardSelector(content: content, state: d.state).select(adverb, now: d.now, rng: &rng)
        #expect(card?.id == "gen:recall:w:u00-a1")
        #expect(card?.format == .recall)
        #expect(card?.isGenerated == true)
    }

    func exercise(_ id: ExerciseID, _ format: ExerciseFormat) -> ContentIndex.Exercise {
        ContentIndex.Exercise(id: id, format: format, unitId: "u00", targets: [ItemSkillPair("w:x", .recall)])
    }

    @Test func rotatesToTheFormatLeastRecentlyUsedForTheItem() {
        let pool = [exercise("e.recall", .recall), exercise("e.cloze", .cloze), exercise("e.build", .sentenceBuilding),
                    exercise("e.choice", .choice)]
        let pair = ItemSkillPair("w:x", .recall)
        // No history: preference order; non-preferred formats only when nothing preferred is left.
        let fresh = CardSelector(content: content, state: LearnerState())
        #expect(fresh.rank(pool, for: pair).map(\.id) == ["e.recall", "e.cloze", "e.build"])
        #expect(fresh.rank([pool[3]], for: pair).map(\.id) == ["e.choice"])
        // Recall used yesterday, cloze last week: sentence-building (never used) wins, then cloze, then recall.
        var state = LearnerState()
        state.formatLastUsed["w:x"] = [.recall: mondayNine - day, .cloze: mondayNine - 7 * day]
        let rotated = CardSelector(content: content, state: state)
        #expect(rotated.rank(pool, for: pair).map(\.id) == ["e.build", "e.cloze", "e.recall"])
        // Within a format: the exercise shown least recently, then by ID.
        let two = [exercise("e.cloze2", .cloze), exercise("e.cloze1", .cloze)]
        #expect(rotated.rank(two, for: pair).map(\.id) == ["e.cloze1", "e.cloze2"])
        state.exerciseHistory["e.cloze1"] = ExerciseHistory(lastAt: mondayNine, attempts: 1, firstTryCorrect: 1,
                                                            lastOutcome: .correct, lastContext: .review)
        #expect(CardSelector(content: content, state: state).rank(two, for: pair).map(\.id)
                == ["e.cloze2", "e.cloze1"])
    }

    @Test func formatUseComesFromFirstAttempts() {
        let d = device()
        d.answer(C.ex(0, 13), .correct, pairOutcomes: [.correct, .correct])
        d.answer(C.ex(0, 7), .wrong)
        d.answer(C.ex(0, 7), .correct, attemptIndex: 2)
        #expect(d.state.formatLastUsed[C.noun(0, 1)]?[.match] != nil)
        #expect(d.state.formatLastUsed[C.noun(0, 2)]?[.match] != nil)
        #expect(d.state.formatLastUsed[C.noun(0, 1)]?[.dictation] == d.events[d.events.count - 2].at)
    }

    @Test func speechOnlyFormatsNeedSpeech() {
        let d = device()
        let pair = ItemSkillPair(C.chunk(0), .speak)
        #expect(CardSelector(content: content, state: d.state).candidates(for: pair, now: d.now).count == 1)
        #expect(CardSelector(content: content, state: d.state, device: .init(speechAvailable: false))
            .candidates(for: pair, now: d.now).isEmpty)
        #expect(CardSelector(content: content, state: d.state, device: .init(speechAvailable: true,
                                                                             speechEnabled: false))
            .candidates(for: pair, now: d.now).isEmpty)
    }

    @Test func grammarPointsWithoutAnEligibleExerciseWait() {
        let d = device()
        d.answer(C.ex(0, 1), .correct)
        d.answer(C.ex(0, 12), .correct)
        let selector = CardSelector(content: content, state: d.state)
        let pair = ItemSkillPair(C.grammarP(0), .recall)
        #expect(!selector.hasCard(for: pair, now: d.now + day))
        var rng = SplitMix64(seed: 3)
        #expect(selector.select(pair, now: d.now + day, rng: &rng) == nil)
        #expect(selector.hasCard(for: pair, now: d.now + 2 * day))
    }

    @Test func generatedListenAndReadCards() throws {
        let d = device()
        d.run(C.step(0, "sounds"))
        var rng = SplitMix64(seedString: "session")
        let selector = CardSelector(content: content, state: d.state)
        // Bank sound-pair exercises were just shown; the listen card is generated.
        let listen = try #require(selector.select(ItemSkillPair(C.sound(0), .listen), now: d.now, rng: &rng))
        #expect(listen.id == "gen:listen:s:u00-s")
        #expect(listen.format == .soundPair)
        d.answer(C.ex(0, 10), .correct)  // the story word's only bank exercise, shown now
        let after = CardSelector(content: content, state: d.state)
        let read = try #require(after.select(ItemSkillPair(C.storyWord(0), .read), now: d.now + day, rng: &rng))
        guard case .generated(.read(let card)) = read else {
            Issue.record("expected a generated read card")
            return
        }
        // Distractors only from eligible items (introduced for read).
        let eligibleGlosses = Set(after.readDistractorPool().map(\.primaryGloss))
        #expect(card.options.allSatisfy { eligibleGlosses.contains($0) })
        #expect(card.options.count == 4)
    }
}
