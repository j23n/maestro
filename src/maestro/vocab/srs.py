from datetime import date, timedelta
from maestro.models import UserVocabularyCard


def review(card: UserVocabularyCard, rating: int) -> UserVocabularyCard:
    """
    Apply one SM-2 review cycle to a card.

    rating: 1–5
      1-2 = failed (reset streak)
      3   = hard but correct
      4   = correct
      5   = easy

    Returns the updated (but not yet saved) card.
    """
    if rating < 3:
        card.repetitions = 0
        card.interval = 1
    else:
        card.repetitions += 1
        if card.repetitions == 1:
            card.interval = 1
        elif card.repetitions == 2:
            card.interval = 6
        else:
            card.interval = round(card.interval * card.ease_factor)
    card.ease_factor = card.ease_factor + (
        0.1 - (5 - rating) * (0.08 + (5 - rating) * 0.02)
    )
    card.ease_factor = max(1.3, card.ease_factor)

    card.next_review = date.today() + timedelta(days=card.interval)

    return card
