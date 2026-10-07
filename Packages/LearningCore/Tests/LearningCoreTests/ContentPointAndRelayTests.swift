import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Other graders: content points (talk, writing), the writing extras and English relay answers.
@Suite struct ContentPointAndRelayTests {
    /// The points of `u02.task.talk` (content/units/02-al-bar/task.yaml).
    static func talkPoints() throws -> [ContentPointMatcher.Point] {
        [
            try .init(id: "greet", accept: ["{buongiorno|buonasera}"]),
            try .init(
                id: "order",
                accept: [
                    "{un {caffè|cappuccino|cornetto}|una spremuta} e {un {caffè|cappuccino|cornetto}|una spremuta}"
                ]),
            try .init(id: "price", accept: ["{quant'è|quanto è|quanto costa}"]),
        ]
    }

    let matcher = ContentPointMatcher()

    @Test func talkModelAnswerFindsEveryPoint() throws {
        let model = "Buongiorno! Vorrei un cappuccino e una spremuta, per favore. Quant'è?"
        let result = matcher.match(response: model, points: try Self.talkPoints(), pass: 2)
        #expect(result.found == ["greet", "order", "price"])
        #expect(result.missing.isEmpty)
        #expect(result.passed)
        #expect(result.fraction == 1)
    }

    @Test func pointsIgnoreAccentsButNeedContiguousTokens() throws {
        let points = try Self.talkPoints()
        let partial = matcher.match(response: "buongiorno, un caffe e un cornetto", points: points, pass: 2)
        #expect(partial.found == ["greet", "order"])
        #expect(partial.missing == ["price"])
        #expect(partial.passed)
        // "un caffè, poi un cornetto" doesn't contain "un caffè e un cornetto" contiguously.
        let gap = matcher.match(response: "un caffè poi un cornetto", points: points, pass: 2)
        #expect(gap.found.isEmpty)
        #expect(!gap.passed)
        #expect(gap.fraction == 0)
        let one = matcher.match(response: "quanto costa", points: points, pass: 2)
        #expect(one.fraction == 0.5)
    }

    @Test func pointsWithSlots() throws {
        let opening = try ContentPointMatcher.Point(id: "opening", accept: ["{caro|cara} {NAME}"])
        #expect(matcher.match(response: "Cara Giulia, come stai?", points: [opening], pass: 1).passed)
        #expect(!matcher.match(response: "Ciao Giulia", points: [opening], pass: 1).passed)
        let age = try ContentPointMatcher.Point(id: "age", accept: ["ho {NUMBER} anni"])
        #expect(matcher.match(response: "Ho 30 anni e abito a Bologna.", points: [age], pass: 1).passed)
        #expect(matcher.match(response: "ho diciassette anni", points: [age], pass: 1, spoken: true).passed)
    }

    /// Talk comes from speech: consonant length is ignored, as for transcripts. Writing is typed: it isn't.
    @Test func spokenPointsIgnoreDoubleConsonants() throws {
        let points = try Self.talkPoints()
        let heard = "buongiorno vorrei un capuccino e un cornetto quanto costa"
        let spoken = matcher.match(response: heard, points: points, pass: 2, spoken: true)
        #expect(spoken.found == ["greet", "order", "price"])
        #expect(matcher.match(response: heard, points: points, pass: 2).found == ["greet", "price"])
    }

    @Test func pointsReadNumbersEitherWay() throws {
        let time = try ContentPointMatcher.Point(id: "time", accept: ["alle {otto|nove} e trenta"])
        #expect(matcher.match(response: "Arrivo alle 8.30.", points: [time], pass: 1).passed)
        let order = try ContentPointMatcher.Point(id: "order", accept: ["{un caffè|una spremuta}"])
        #expect(matcher.match(response: "1 spremuta, grazie", points: [order], pass: 1, spoken: true).passed)
        let price = try ContentPointMatcher.Point(id: "price", accept: ["sei euro e venti"])
        #expect(matcher.match(response: "sono 6.20", points: [price], pass: 1).passed)
    }

    @Test func writingWordCountAndSuggestions() {
        #expect(WritingChecker.wordCount("Cara Giulia, la mia famiglia è grande!") == 7)
        #expect(WritingChecker.wordCount(" — ") == 0)
        let forms = KnownForms([
            "la": ["w:la"], "mia": ["w:mio"], "famiglia": ["w:famiglia"], "è": ["w:essere"], "grande": ["w:grande"],
            "perché": ["w:perche"],
        ])
        let suggestions = WritingChecker.spellingSuggestions("La mia famiglia è grade perche 3", knownForms: forms)
        #expect(suggestions.map(\.token) == ["grade", "perche"])
        #expect(suggestions.map(\.suggestion) == ["grande", "perché"])
        #expect(suggestions.first?.message == "Did you mean grande?")
        #expect(suggestions.map(\.tokenIndex) == [4, 5])
        #expect(WritingChecker.spellingSuggestions("la famigla", knownForms: forms).first?.suggestion == "famiglia")
        #expect(WritingChecker.spellingSuggestions("Bologna", knownForms: forms).isEmpty)
    }

    @Test func knownFormsSuggestionsCoverEveryEdit() {
        let forms = KnownForms(["cappuccino": ["w:cappuccino"], "caffè": ["w:caffe"]])
        #expect(forms.suggestions(for: "capuccino") == ["cappuccino"])  // deletion
        #expect(forms.suggestions(for: "cappuccinno") == ["cappuccino"])  // insertion
        #expect(forms.suggestions(for: "cappuccnio") == ["cappuccino"])  // transposition
        #expect(forms.suggestions(for: "caffe") == ["caffè"])  // substitution (an accent is a letter)
        #expect(forms.suggestions(for: "caffè").isEmpty)
        #expect(forms.suggestions(for: "cafe").isEmpty)  // two edits
    }

    // MARK: - Relay (English answers)

    typealias Answer = EnglishAnswerGrader.Answer

    @Test func relayTimes() {
        let t = Answer.time(hour: 22, minute: 15)
        #expect(EnglishAnswerGrader.isCorrect("It leaves at 22:15.", answer: t))
        #expect(EnglishAnswerGrader.isCorrect("10.15 pm", answer: t))
        #expect(EnglishAnswerGrader.isCorrect("at 10 15", answer: t))
        #expect(!EnglishAnswerGrader.isCorrect("at 10:45", answer: t))
        #expect(!EnglishAnswerGrader.isCorrect("at 11:15", answer: t))
        #expect(EnglishAnswerGrader.isCorrect("9:05", answer: .time(hour: 9, minute: 5)))
        #expect(EnglishAnswerGrader.isCorrect("21:05", answer: .time(hour: 9, minute: 5)))
        #expect(!EnglishAnswerGrader.isCorrect("9:5", answer: .time(hour: 9, minute: 5)))
    }

    @Test func relayTimeOnTheHourAcceptsABareHour() {
        let nine = Answer.time(hour: 21, minute: 0)
        #expect(EnglishAnswerGrader.isCorrect("at 9", answer: nine))
        #expect(EnglishAnswerGrader.isCorrect("9 pm", answer: nine))
        #expect(EnglishAnswerGrader.isCorrect("Nine o'clock", answer: nine))
        #expect(EnglishAnswerGrader.isCorrect("21.00", answer: nine))
        #expect(!EnglishAnswerGrader.isCorrect("at 8", answer: nine))
        // Not when the minutes matter, and an hour inside a time is not a bare hour.
        #expect(!EnglishAnswerGrader.isCorrect("at 9", answer: .time(hour: 9, minute: 30)))
        #expect(!EnglishAnswerGrader.isCorrect("at 9:30", answer: .time(hour: 9, minute: 0)))
    }

    @Test func relayPrices() {
        let p = Answer.price(1.60)
        #expect(EnglishAnswerGrader.isCorrect("1,60", answer: p))
        #expect(EnglishAnswerGrader.isCorrect("It's €1.60", answer: p))
        #expect(EnglishAnswerGrader.isCorrect("1.6 euros", answer: p))
        #expect(!EnglishAnswerGrader.isCorrect("1.40 euros", answer: p))
        #expect(EnglishAnswerGrader.isCorrect("3 euros", answer: .price(3)))
        #expect(EnglishAnswerGrader.grade("two cappuccinos at 1.40", answer: .price(1.40)).outcome == .correct)
        #expect(EnglishAnswerGrader.grade("no idea", answer: .price(1.40)).outcome == .wrong)
    }

    @Test func relayNumbersAndText() {
        #expect(EnglishAnswerGrader.isCorrect("platform 3", answer: .number(3)))
        #expect(!EnglishAnswerGrader.isCorrect("platform 4", answer: .number(3)))
        #expect(EnglishAnswerGrader.isCorrect("Three of them", answer: .number(3)))
        #expect(EnglishAnswerGrader.isCorrect("twenty-one", answer: .number(21)))
        #expect(EnglishAnswerGrader.isCorrect("twenty one", answer: .number(21)))
        #expect(EnglishAnswerGrader.isCorrect("forty", answer: .number(40)))
        #expect(!EnglishAnswerGrader.isCorrect("someone", answer: .number(1)))
        #expect(EnglishAnswerGrader.isCorrect("three euros", answer: .price(3)))
        let text = Answer.text(["a cappuccino", "cappuccino"])
        #expect(EnglishAnswerGrader.isCorrect("She wants a CAPPUCCINO, please!", answer: text))
        #expect(EnglishAnswerGrader.isCorrect("Cappuccino.", answer: text))
        #expect(!EnglishAnswerGrader.isCorrect("an espresso", answer: text))
        let ordered = Answer.text(["left then right"])
        #expect(EnglishAnswerGrader.isCorrect("turn left and then go right", answer: ordered))
        #expect(!EnglishAnswerGrader.isCorrect("right then left", answer: ordered))
        #expect(EnglishAnswerGrader.isCorrect("It’s Luca’s", answer: .text(["it's luca's"])))
    }
}
