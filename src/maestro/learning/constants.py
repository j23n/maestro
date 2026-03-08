"""Shared constants for the learning subsystem."""

MACRO_CATEGORIES: dict[str, tuple[str, str]] = {
    "interagire_informazioni": (
        "exchanging factual information",
        "exchanging information",
    ),
    "interagire_opinioni_atteggiamenti": (
        "expressing opinions and attitudes",
        "expressing opinions",
    ),
    "interagire_emozioni_sentimenti": (
        "expressing emotions and feelings",
        "expressing emotions",
    ),
    "interagire_attivita_azioni": (
        "coordinating actions and activities",
        "coordinating actions",
    ),
    "interagire_rituali_sociali": (
        "social rituals (greetings, thanks, etc.)",
        "social rituals",
    ),
    "strutturare_discorso": (
        "structuring discourse (connectors, topic shifts)",
        "structuring discourse",
    ),
    "strutturare_interazione_verbale": (
        "managing verbal interaction (turn-taking)",
        "managing conversation",
    ),
}
