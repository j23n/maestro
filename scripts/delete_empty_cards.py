"""
Delete UserVocabularyCards with dangling VocabularyWord links.
"""

import asyncio
from maestro.db import init_db
from maestro.models import UserVocabularyCard, VocabularyWord


async def main():
    await init_db()
    cards = await UserVocabularyCard.find_all().to_list()
    for card in cards:
        await card.fetch_all_links()

    empty = [card for card in cards if not isinstance(card.word, VocabularyWord)]
    print(f"Found {len(empty)} empty card(s) out of {len(cards)} total")

    for card in empty:
        await card.delete()
        print(f"  deleted {card.id}")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
