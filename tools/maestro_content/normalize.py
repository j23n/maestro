"""Text normalisation shared by the pipeline. The app mirrors fold() in LanguageCore."""

import unicodedata

APOSTROPHES = {"’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'"}


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def apostrophes(text: str) -> str:
    for src, dst in APOSTROPHES.items():
        text = text.replace(src, dst)
    return text


def fold(text: str) -> str:
    """Lowercase, straight apostrophes, no diacritics, ß as ss: the key for accent-insensitive lookup."""
    decomposed = unicodedata.normalize("NFD", apostrophes(text).lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").replace("ß", "ss")


def german_key(text: str) -> str:
    """The key for a German drill: lowercase, ß as ss, ae/oe/ue as umlauts, umlauts kept (hatte isn't
    hätte). The app's DrillGrader.germanKey mirrors it."""
    key = nfc(apostrophes(text).lower()).replace("ß", "ss")
    return key.replace("ae", "ä").replace("oe", "ö").replace("ue", "ü")


def drill_key(text: str, topic: str) -> str:
    """The key a drill's answers, options and near-misses are compared with: German drills keep umlauts."""
    return german_key(text) if topic.startswith("de:") else fold(text)


def utf16_len(text: str) -> int:
    """Length in UTF-16 code units, the unit pack ranges use (Python's len() counts code points)."""
    return len(text.encode("utf-16-le")) // 2


def utf16_slice(text: str, start: int, length: int) -> str:
    data = text.encode("utf-16-le")
    return data[2 * start : 2 * (start + length)].decode("utf-16-le")
