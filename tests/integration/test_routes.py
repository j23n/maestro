"""FastAPI route smoke tests using mongomock DB and patched lifespan."""

import pytest

# test_app fixture is provided by tests/integration/conftest.py


@pytest.mark.integration
def test_vocab_page_ok(test_app):
    response = test_app.get("/vocab")
    assert response.status_code == 200


@pytest.mark.integration
def test_vocab_word_not_found(test_app):
    response = test_app.get("/vocab/word/NONEXISTENT-ID")
    assert response.status_code == 404


@pytest.mark.integration
def test_profilo_page_ok(test_app):
    """Profile page renders even with no profile in DB."""
    response = test_app.get("/profilo")
    assert response.status_code == 200


@pytest.mark.integration
def test_grammar_nonexistent_returns_404(test_app):
    response = test_app.get("/grammar/NONEXISTENT")
    assert response.status_code == 404


@pytest.mark.integration
def test_lezione_index_no_active_shows_config(test_app):
    """With no active lesson, /lezione/ should show the lesson config screen."""
    response = test_app.get("/lezione/", follow_redirects=False)
    assert response.status_code == 200
    # A0 student with no progress sees the welcome card + first-lesson button
    assert (
        "Start your first lesson" in response.text
        or "Inizia la tua prima lezione" in response.text
    )
