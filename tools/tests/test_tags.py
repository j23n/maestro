from maestro_content import tags


def test_kaikki_simple_tenses():
    k = tags.kaikki_form_tag
    assert k(["first-person", "indicative", "present", "singular"]) == "ind.pres.1s"
    assert k(["first-person", "imperfect", "indicative", "plural"]) == "ind.impf.1p"
    assert k(["historic", "indicative", "past", "third-person", "singular"]) == "ind.prem.3s"
    assert k(["future", "indicative", "second-person", "plural"]) == "ind.fut.2p"
    assert k(["conditional", "present", "first-person", "plural"]) == "cond.pres.1p"
    assert k(["subjunctive", "imperfect", "third-person", "plural"]) == "sub.impf.3p"
    assert k(["present", "subjunctive", "first-person", "singular"]) == "sub.pres.1s"


def test_kaikki_nonfinite_and_imperative():
    k = tags.kaikki_form_tag
    assert k(["infinitive"]) == "inf.pres"
    assert k(["gerund"]) == "ger.pres"
    assert k(["participle", "past", "feminine", "singular"]) == "part.pass"
    assert k(["participle", "present"]) == "part.pres"
    assert k(["imperative", "second-person", "singular"]) == "imp.pres.2s"
    assert k(["imperative", "negative", "second-person", "singular"]) == "imp.neg.2s"
    assert k(["imperative", "first-person", "singular"]) is None


def test_kaikki_skips_compound_and_helper_forms():
    k = tags.kaikki_form_tag
    assert k(["indicative", "perfect", "first-person", "singular", "multiword-construction"]) is None
    assert k(["auxiliary"]) is None
    assert k(["canonical"]) is None


def test_morphit_passato_remoto_is_not_a_compound_tense():
    assert tags.morphit_tag("VER:ind+past+3+s") == "ind.prem.3s"
    assert tags.morphit_tag("VER:ind+pres+1+p") == "ind.pres.1p"
    assert tags.morphit_tag("VER:impr+pres+2+s") == "imp.pres.2s"
    assert tags.morphit_tag("VER:part+past+s+f") == "part.pass"
    assert tags.morphit_tag("VER:inf+pres") == "inf.pres"
    assert tags.morphit_tag("VER:ger+pres-cli") is None
    assert tags.morphit_tag("NOUN-M:p") == "mp"
    assert tags.morphit_tag("ADJ:pos+f+s") == "fs"


def test_is_valid():
    for good in ("ind.pres.1s", "cond.pass.1p", "sub.tpp.1s", "imp.neg.2s", "part.pass", "ind.pp.3s+e"):
        assert tags.is_valid(good), good
    for bad in ("ind.pres", "part.pass.1s", "xx.pres.1s", "ind.pp.3s+x", "cond.pass.4p"):
        assert not tags.is_valid(bad), bad
