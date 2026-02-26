"""
Rebuild UserVocabularyCards from annotated message spans.

Scans assistant messages for vocab spans (both old title= and new data-* formats),
finds the first message each word appeared in, and creates a UserVocabularyCard
linked to the matching VocabularyWord. Words with no VocabularyWord are skipped.

Run after migrate_vocab_spans.py if you want consistent data-* attributes,
though this script handles both span formats independently.
"""

import asyncio
import re
from maestro.db import init_db
from maestro.models import Message, VocabularyWord, UserVocabularyCard


# Matches old format: title="translation — definition"
OLD_SPAN = re.compile(r'<span class="vocab-word" title="[^"]+">([^<]+)</span>')
# Matches new format: data-word="..."
NEW_SPAN = re.compile(r'<span class="vocab-word"[^>]*\bdata-word="([^"]+)"')


def extract_words(text: str) -> set[str]:
    words = set()
    words.update(m.group(1).lower() for m in OLD_SPAN.finditer(text))
    words.update(m.group(1).lower() for m in NEW_SPAN.finditer(text))
    return words


async def main():
    await init_db()

    # Find first message each word appeared in (chronological order)
    messages = await Message.find({"sender": "assistant"}).sort("created_at").to_list()
    word_to_message: dict[str, Message] = {}
    for msg in messages:
        for word in extract_words(msg.text):
            if word not in word_to_message:
                word_to_message[word] = msg

    print(f"Found {len(word_to_message)} unique annotated word(s) across messages\n")

    # Collect IDs of words that already have cards
    existing_cards = await UserVocabularyCard.find_all().to_list()
    existing_word_ids = {card.word.ref.id for card in existing_cards}

    created = skipped = missing = 0
    for word_str, message in word_to_message.items():
        vocab_word = await VocabularyWord.find_one({"word": word_str})
        if not vocab_word:
            print(f"  no VocabularyWord for '{word_str}' — skipping")
            missing += 1
            continue
        if vocab_word.id in existing_word_ids:
            skipped += 1
            continue
        await UserVocabularyCard(
            word=vocab_word,
            message=message,
            discovered_at=message.created_at,
        ).insert()
        existing_word_ids.add(vocab_word.id)
        print(f"  created card: '{word_str}'")
        created += 1

    print(f"\nDone — {created} created, {skipped} already existed, {missing} skipped (no VocabularyWord).")


if __name__ == "__main__":
    asyncio.run(main())
