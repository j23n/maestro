"""
Migrate vocab word spans from title attribute to data-* attributes.

Old: <span class="vocab-word" title="translation — definition">word</span>
New: <span class="vocab-word" data-word="word" data-definition="definition" data-translation="translation">word</span>
"""

import asyncio
import re
from maestro.db import init_db
from maestro.models import Message


PATTERN = re.compile(
    r'<span class="vocab-word" title="([^"]+)">([^<]+)</span>'
)


def upgrade(text: str) -> tuple[str, int]:
    count = 0

    def replace(m: re.Match) -> str:
        nonlocal count
        title, word = m.group(1), m.group(2)
        parts = title.split(" — ", 1)
        translation = parts[0]
        definition = parts[1] if len(parts) > 1 else ""
        count += 1
        return (
            f'<span class="vocab-word"'
            f' data-word="{word}"'
            f' data-definition="{definition}"'
            f' data-translation="{translation}">'
            f"{word}</span>"
        )

    return PATTERN.sub(replace, text), count


async def main():
    await init_db()
    messages = await Message.find_all().to_list()
    updated = 0
    for msg in messages:
        new_text, n = upgrade(msg.text)
        if n > 0:
            msg.text = new_text
            await msg.save()
            updated += 1
            print(f"  {msg.id}: {n} span(s) upgraded")
    print(f"\nDone — {updated} message(s) updated.")


if __name__ == "__main__":
    asyncio.run(main())
