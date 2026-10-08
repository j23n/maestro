"""Display forms (docs/03 § Display forms) and generated recall answers (docs/05 § Review session builder,
docs/06 § 1). The recall cases mirror LearningCore's GeneratedCardTests, so preview retrievals and generated review
cards accept the same answers."""

from __future__ import annotations

import pytest

from itcontent.pack.display import NearAnswer, display_forms, noun_recall, recall_answer


def noun(it: str, gender: str, **kw) -> dict:
    return {"it": it, "pos": "noun", "gender": gender, **kw}


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (noun("cornetto", "m"), ("il cornetto", "un cornetto")),
        (noun("spremuta", "f"), ("la spremuta", "una spremuta")),
        (noun("caffè", "m"), ("il caffè", "un caffè")),
        (noun("zaino", "m"), ("lo zaino", "uno zaino")),
        (noun("studente", "m"), ("lo studente", "uno studente")),
        (noun("gnocco", "m"), ("lo gnocco", "uno gnocco")),
        (noun("acqua", "f"), ("l'acqua (f)", "un'acqua")),
        (noun("albero", "m"), ("l'albero (m)", "un albero")),
        (noun("hotel", "m"), ("l'hotel (m)", "un hotel")),
        (noun("amico", "mf", forms=["amica", "amici", "amiche"]), ("l'amico / l'amica", "un amico / un'amica")),
        (noun("ragazzo", "mf", forms=["ragazza"]), ("il ragazzo / la ragazza", "un ragazzo / una ragazza")),
        (noun("signore", "mf", forms=["signora"]), ("il signore / la signora", "un signore / una signora")),
        (noun("turista", "mf"), ("il turista / la turista", "un turista / una turista")),
        (noun("artista", "mf"), ("l'artista (m/f)", "un artista / un'artista")),
        (noun("yogurt", "m", articles={"def": "lo", "indef": "uno"}), ("lo yogurt", "uno yogurt")),
        ({"it": "oggi", "pos": "adv"}, (None, None)),
    ],
)
def test_display_forms(item, expected):
    assert display_forms(item) == expected


def test_masculine_noun():
    answer, near = recall_answer(noun("cornetto", "m"), "word")
    assert answer == "{il|un} [cornetto]"
    assert near == [
        NearAnswer("cornetto", "correctWithNote", "Say it with its article: il cornetto"),
        NearAnswer("{la cornetto|una cornetto}", "almost", "cornetto is masculine: il cornetto"),
    ]


def test_feminine_noun():
    answer, near = recall_answer(noun("spremuta", "f"), "word")
    assert answer == "{la|una} [spremuta]"
    assert near[1] == NearAnswer(
        "{il spremuta|lo spremuta|un spremuta|uno spremuta}", "almost", "spremuta is feminine: la spremuta"
    )


def test_elided_articles_and_the_gender_mark():
    answer, near = noun_recall("f", "l'acqua (f)", "un'acqua")
    assert answer == "{[l'acqua]|[un'acqua]}"
    assert near[0] == NearAnswer("acqua", "correctWithNote", "Say it with its article: l'acqua")
    assert near[1].answer == "{il acqua|lo acqua|un acqua|uno acqua}"
    answer, near = noun_recall("m", "l'albero", "un albero")
    assert answer == "{[l'albero]|un [albero]}"
    assert near[1].answer == "{la albero|una albero|un'albero}"  # l' fits both genders; un' is wrong


def test_lo_nouns_and_people():
    assert noun_recall("m", "lo zaino", "uno zaino")[0] == "{lo|uno} [zaino]"
    answer, near = noun_recall("mf", "il ragazzo / la ragazza", "un ragazzo / una ragazza")
    assert answer == "{il [ragazzo]|la [ragazza]|un [ragazzo]|una [ragazza]}"
    assert near == [NearAnswer("{ragazzo|ragazza}", "correctWithNote", "Say it with its article: il ragazzo")]


def test_recall_answer_overrides_and_other_kinds():
    amico = noun("amico", "mf", recall_answer="{l'amico|l'amica|un amico|un'amica}")
    assert recall_answer(amico, "word") == ("{l'amico|l'amica|un amico|un'amica}", [])
    assert recall_answer({"it": "oggi", "pos": "adv"}, "word") == ("[oggi]", [])
    assert recall_answer({"it": "quant'è?"}, "chunk") == ("quant'è", [])
    assert recall_answer({"it": "ti piace…?"}, "chunk") == ("ti piace", [])
    assert recall_answer({"it": "come si dice (in italiano)?"}, "chunk") == (r"come si dice \(in italiano\)", [])
    assert recall_answer({"it": "tu/Lei"}, "chunk") is None  # lint requires recall_answer
    assert recall_answer({"it": "un, una"}, "grammar") is None
    assert recall_answer({"it": "consonanti doppie"}, "sound") is None
