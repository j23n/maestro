"""Text normalisation shared by the pipeline. The app mirrors fold() in ItalianCore."""

import unicodedata

APOSTROPHES = {"’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'"}


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def apostrophes(text: str) -> str:
    for src, dst in APOSTROPHES.items():
        text = text.replace(src, dst)
    return text


def fold(text: str) -> str:
    """Lowercase, straight apostrophes, no diacritics: the key for accent-insensitive lookup."""
    decomposed = unicodedata.normalize("NFD", apostrophes(text).lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def utf16_len(text: str) -> int:
    """Length in UTF-16 code units, the unit pack ranges use (Python's len() counts code points)."""
    return len(text.encode("utf-16-le")) // 2


def utf16_slice(text: str, start: int, length: int) -> str:
    data = text.encode("utf-16-le")
    return data[2 * start : 2 * (start + length)].decode("utf-16-le")
