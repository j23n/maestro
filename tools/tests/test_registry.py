from maestro_content.registry import Registry, base_lemma_id, sense_fingerprint


def test_lemma_ids_and_homographs():
    reg = Registry()
    assert reg.lemma_id("pesca", "n", "pesca|n|peach") == "it:pesca:n"
    assert reg.lemma_id("pesca", "n", "pesca|n|fishing") == "it:pesca:n:2"
    assert base_lemma_id("Bologna", "propn") == "it:Bologna:propn"
    assert base_lemma_id("essere d'accordo", "phr") == "it:essere_d'accordo:phr"


def test_homograph_numbers_survive_reordering(tmp_path):
    reg = Registry()
    reg.lemma_id("pesca", "n", "peach")
    reg.lemma_id("pesca", "n", "fishing")
    reg.save(str(tmp_path))
    again = Registry.load(str(tmp_path))
    # the new dump lists fishing first; it keeps its number
    assert again.lemma_id("pesca", "n", "fishing") == "it:pesca:n:2"
    assert again.lemma_id("pesca", "n", "peach") == "it:pesca:n"


def test_sense_codes_are_deterministic_and_prefer_source_ids():
    fp = sense_fingerprint(None, None, "it:andare:v", "to go")
    a = Registry().sense_id("it:andare:v", fp, "to go")
    b = Registry().sense_id("it:andare:v", fp, "to go")
    assert a == b and a.startswith("it:andare:v#") and len(a.split("#")[1]) == 4
    assert sense_fingerprint("x1", "Q1", "it:a:v", "g") == "senseid:x1"
    assert sense_fingerprint(None, "Q1", "it:a:v", "g") == "wikidata:Q1"


def test_retired_senses_are_reported(tmp_path):
    reg = Registry()
    old = reg.sense_id("it:andare:v", "gloss:old", "to walk")
    reg.save(str(tmp_path))
    again = Registry.load(str(tmp_path))
    again.sense_id("it:andare:v", "gloss:new", "to go")
    assert (old, "to walk") in again.retired_senses()
