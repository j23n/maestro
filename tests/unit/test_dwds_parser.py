"""Unit tests for maestro.vocab.dwds_parser — DWDS web page parsing."""

import pytest

from maestro.vocab.dwds_parser import parse_html


@pytest.fixture
def haus_html():
    """Minimal DWDS-like HTML for 'Haus' (single article, noun)."""
    return """
    <div class="dwdswb-artikel">
      <div class="dwdswb-ft-blocks">
        <div class="dwdswb-ft-block">
          <span class="dwdswb-ft-blocktext">
            Substantiv (Neutrum) · Genitiv Singular: Hauses · Nominativ Plural: Häuser
          </span>
        </div>
      </div>
      <div class="dwdswb-lesarten">
        <div class="dwdswb-lesart">
          <div class="dwdswb-lesart-n">1.</div>
          <div class="dwdswb-lesart-def">
            <span class="dwdswb-definition">Gebäude zum Wohnen</span>
          </div>
          <div class="dwdswb-lesart-content">
            <div class="dwdswb-verwendungsbeispiele">
              <div class="dwdswb-kompetenzbeispiel">ein großes Haus</div>
              <div class="dwdswb-kompetenzbeispiel">das Haus steht am See</div>
            </div>
          </div>
        </div>
        <div class="dwdswb-lesart">
          <div class="dwdswb-lesart-n">2.</div>
          <div class="dwdswb-lesart-def">
            <span class="dwdswb-definition">Hauswesen, Familie</span>
          </div>
          <div class="dwdswb-lesart-content"></div>
        </div>
      </div>
    </div>
    """


@pytest.fixture
def bank_html():
    """Minimal DWDS-like HTML for 'Bank' (two homograph articles)."""
    return """
    <div class="dwdswb-artikel">
      <div class="dwdswb-ft-blocks">
        <div class="dwdswb-ft-block">
          <span class="dwdswb-ft-blocktext">Substantiv (Femininum) · Nominativ Plural: Bänke</span>
        </div>
      </div>
      <div class="dwdswb-lesarten">
        <div class="dwdswb-lesart">
          <div class="dwdswb-lesart-def">
            <span class="dwdswb-definition">Sitz für mehrere Personen</span>
          </div>
          <div class="dwdswb-lesart-content"></div>
        </div>
      </div>
    </div>
    <div class="dwdswb-artikel">
      <div class="dwdswb-ft-blocks">
        <div class="dwdswb-ft-block">
          <span class="dwdswb-ft-blocktext">Substantiv (Femininum) · Nominativ Plural: Banken</span>
        </div>
      </div>
      <div class="dwdswb-lesarten">
        <div class="dwdswb-lesart">
          <div class="dwdswb-lesart-def">
            <span class="dwdswb-definition">Unternehmen für Geldgeschäfte</span>
          </div>
          <div class="dwdswb-lesart-content"></div>
        </div>
      </div>
    </div>
    """


@pytest.fixture
def verb_html():
    """Minimal DWDS-like HTML for a verb."""
    return """
    <div class="dwdswb-artikel">
      <div class="dwdswb-ft-blocks">
        <div class="dwdswb-ft-block">
          <span class="dwdswb-ft-blocktext">Verb · läuft, lief, ist gelaufen</span>
        </div>
      </div>
      <div class="dwdswb-lesarten">
        <div class="dwdswb-lesart">
          <div class="dwdswb-lesart-def">
            <span class="dwdswb-definition">sich zu Fuß fortbewegen</span>
          </div>
          <div class="dwdswb-lesart-content">
            <div class="dwdswb-lesart">
              <div class="dwdswb-lesart-content">
                <div class="dwdswb-verwendungsbeispiele">
                  <div class="dwdswb-kompetenzbeispiel">das Kind kann schon laufen</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    """


class TestParseHtml:
    def test_single_article_noun(self, haus_html):
        entries = parse_html(haus_html, "Haus")
        assert len(entries) == 1
        e = entries[0]
        assert e.headword == "Haus"
        assert e.pos_abbrev == "Subst."
        assert e.entry_id == "DWDS-Haus-0"
        assert len(e.senses) == 2

    def test_senses_extracted(self, haus_html):
        entries = parse_html(haus_html, "Haus")
        senses = entries[0].senses
        assert senses[0].definition == "Gebäude zum Wohnen"
        assert senses[1].definition == "Hauswesen, Familie"

    def test_examples_extracted(self, haus_html):
        entries = parse_html(haus_html, "Haus")
        examples = entries[0].senses[0].examples
        assert len(examples) == 2
        assert "ein großes Haus" in examples[0]

    def test_sense_without_examples(self, haus_html):
        entries = parse_html(haus_html, "Haus")
        assert entries[0].senses[1].examples == []

    def test_homograph_separation(self, bank_html):
        entries = parse_html(bank_html, "Bank")
        assert len(entries) == 2
        assert entries[0].senses[0].definition == "Sitz für mehrere Personen"
        assert entries[1].senses[0].definition == "Unternehmen für Geldgeschäfte"
        assert entries[0].entry_id == "DWDS-Bank-0"
        assert entries[1].entry_id == "DWDS-Bank-1"

    def test_verb_pos(self, verb_html):
        entries = parse_html(verb_html, "laufen")
        assert len(entries) == 1
        assert entries[0].pos_abbrev == "V."

    def test_examples_from_sub_lesarts(self, verb_html):
        entries = parse_html(verb_html, "laufen")
        assert len(entries[0].senses[0].examples) == 1
        assert "laufen" in entries[0].senses[0].examples[0]

    def test_empty_html_returns_empty(self):
        assert parse_html("<html><body></body></html>", "foo") == []

    def test_pos_without_senses_still_returned(self):
        """Entry with POS but no senses should still be returned."""
        html = """
        <div class="dwdswb-artikel">
          <div class="dwdswb-ft-blocks">
            <div class="dwdswb-ft-block">
              <span class="dwdswb-ft-blocktext">Substantiv</span>
            </div>
          </div>
          <div class="dwdswb-lesarten"></div>
        </div>
        """
        entries = parse_html(html, "test")
        assert len(entries) == 1
        assert entries[0].pos_abbrev == "Subst."
        assert entries[0].senses == []

    def test_no_pos_no_senses_skipped(self):
        """Entry with neither POS nor senses should be skipped."""
        html = """
        <div class="dwdswb-artikel">
          <div class="dwdswb-lesarten"></div>
        </div>
        """
        assert parse_html(html, "test") == []

    def test_compound_pos_indefinitpronomen(self):
        html = """
        <div class="dwdswb-artikel">
          <div class="dwdswb-ft-blocks">
            <div class="dwdswb-ft-block">
              <span class="dwdswb-ft-blocktext">Indefinitpronomen · undeklinierbar</span>
            </div>
          </div>
          <div class="dwdswb-lesarten">
            <div class="dwdswb-lesart">
              <div class="dwdswb-lesart-def">
                <span class="dwdswb-definition">ein wenig</span>
              </div>
              <div class="dwdswb-lesart-content"></div>
            </div>
          </div>
        </div>
        """
        entries = parse_html(html, "etwas")
        assert len(entries) == 1
        assert entries[0].pos_abbrev == "Pron."

    def test_compound_pos_personalpronomen(self):
        html = """
        <div class="dwdswb-artikel">
          <div class="dwdswb-ft-blocks">
            <div class="dwdswb-ft-block">
              <span class="dwdswb-ft-blocktext">Personalpronomen · 1. Person Singular</span>
            </div>
          </div>
          <div class="dwdswb-lesarten">
            <div class="dwdswb-lesart">
              <div class="dwdswb-lesart-def">
                <span class="dwdswb-definition">bezeichnet den Sprecher</span>
              </div>
              <div class="dwdswb-lesart-content"></div>
            </div>
          </div>
        </div>
        """
        entries = parse_html(html, "ich")
        assert len(entries) == 1
        assert entries[0].pos_abbrev == "Pron."

    def test_compound_pos_gradpartikel(self):
        html = """
        <div class="dwdswb-artikel">
          <div class="dwdswb-ft-blocks">
            <div class="dwdswb-ft-block">
              <span class="dwdswb-ft-blocktext">Gradpartikel</span>
            </div>
          </div>
          <div class="dwdswb-lesarten">
            <div class="dwdswb-lesart">
              <div class="dwdswb-lesart-def">
                <span class="dwdswb-definition">drückt eine Einschränkung aus</span>
              </div>
              <div class="dwdswb-lesart-content"></div>
            </div>
          </div>
        </div>
        """
        entries = parse_html(html, "nur")
        assert len(entries) == 1
        assert entries[0].pos_abbrev == "Part."

    def test_definition_spezifizierung(self):
        """Senses using dwdswb-definition-spezifizierung should be extracted."""
        html = """
        <div class="dwdswb-artikel">
          <div class="dwdswb-ft-blocks">
            <div class="dwdswb-ft-block">
              <span class="dwdswb-ft-blocktext">Partikel</span>
            </div>
          </div>
          <div class="dwdswb-lesarten">
            <div class="dwdswb-lesart">
              <div class="dwdswb-lesart-def">
                <span class="dwdswb-definition-spezifizierung">als Antwort auf eine Frage</span>
              </div>
              <div class="dwdswb-lesart-content"></div>
            </div>
          </div>
        </div>
        """
        entries = parse_html(html, "ja")
        assert len(entries) == 1
        assert entries[0].pos_abbrev == "Part."
        assert len(entries[0].senses) == 1
        assert "Antwort" in entries[0].senses[0].definition

    def test_paraphrase_fallback(self):
        """Senses using dwdswb-paraphrase should be extracted as fallback."""
        html = """
        <div class="dwdswb-artikel">
          <div class="dwdswb-ft-blocks">
            <div class="dwdswb-ft-block">
              <span class="dwdswb-ft-blocktext">Partikel</span>
            </div>
          </div>
          <div class="dwdswb-lesarten">
            <div class="dwdswb-lesart">
              <div class="dwdswb-lesart-def">
                <span class="dwdswb-paraphrase">höfliche Aufforderung</span>
              </div>
              <div class="dwdswb-lesart-content"></div>
            </div>
          </div>
        </div>
        """
        entries = parse_html(html, "bitte")
        assert len(entries) == 1
        assert entries[0].pos_abbrev == "Part."
        assert len(entries[0].senses) == 1
        assert "höfliche" in entries[0].senses[0].definition

    def test_adjective_pos(self):
        html = """
        <div class="dwdswb-artikel">
          <div class="dwdswb-ft-blocks">
            <div class="dwdswb-ft-block">
              <span class="dwdswb-ft-blocktext">Adjektiv · Komparativ: besser</span>
            </div>
          </div>
          <div class="dwdswb-lesarten">
            <div class="dwdswb-lesart">
              <div class="dwdswb-lesart-def">
                <span class="dwdswb-definition">von einwandfreier Qualität</span>
              </div>
              <div class="dwdswb-lesart-content"></div>
            </div>
          </div>
        </div>
        """
        entries = parse_html(html, "gut")
        assert entries[0].pos_abbrev == "Adj."
