"""Uzbek Latin -> Cyrillic for the MMS fallback voice (facebook/mms-tts-uzb-script_cyrillic reads Cyrillic only; NLLB
writes Latin). The official 1995 alphabet maps letter by letter, except: oʻ gʻ (any apostrophe), sh ch, yo yu ya ye,
and e is э at the start of a word. MMS spoke 20 FLEURS sentences converted this way with 2.7 % CER heard back (C43)."""
import re

PAIRS = [("o'", "ў"), ("g'", "ғ"), ("sh", "ш"), ("ch", "ч"), ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("ye", "е")]
LETTERS = dict(zip("abdfghijklmnopqrstuvxyz", "абдфгҳижклмнопқрстувхйз"))
APOSTROPHES = re.compile("[‘’ʻʼ`]")


def _word(w: str) -> str:
    out, i = [], 0
    while i < len(w):
        pair = next((c for a, c in PAIRS if w.startswith(a, i)), None)
        if pair:
            out.append(pair)
            i += 2
        else:
            out.append("э" if w[i] == "e" and i == 0 else "е" if w[i] == "e" else LETTERS.get(w[i], w[i]))
            i += 1
    return "".join(out)


def to_cyrillic(text: str) -> str:
    """Lower-case Cyrillic (MMS ignores case); digits and punctuation pass through."""
    return "".join(_word(p) if p.isalpha() or "'" in p else p
                   for p in re.split(r"([^\w']+)", APOSTROPHES.sub("'", text.lower())))
