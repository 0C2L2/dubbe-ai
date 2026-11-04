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


# Numbers as spoken words: Navoiy's own normalizer is not published and num2words has no Uzbek, so "2026-yilda" or "47,9"
# reached the voice as digits and came out wrong. Subtitles keep the digits (only tags.text_for_tts calls this).
ONES = ["", "bir", "ikki", "uch", "to'rt", "besh", "olti", "yetti", "sakkiz", "to'qqiz"]
TENS = ["", "o'n", "yigirma", "o'ttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "to'qson"]
SCALES = [(10 ** 9, "milliard"), (10 ** 6, "million"), (1000, "ming")]
FRACTION = {1: "o'ndan", 2: "yuzdan", 3: "mingdan"}  # 47,9 = qirq yetti butun o'ndan to'qqiz
ENDINGS = {"ga", "da", "dan", "ni", "ning", "gacha", "dagi", "ta", "si", "i", "ka", "qa"}  # "5-da" = at five, not "fifth"
# whole number (thousands grouped by a comma or space before exactly three digits), decimal part, %, ordinal hyphen
NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:[ ,]\d{3})+(?![.,]?\d)|\d+)(?:[.,](\d+))?(\s?%)?(?:-([^\W\d]+))?")
ORDINAL_ENDINGS = {"chi", "nchi", "inchi"}  # "5-chi": already marked as an ordinal


def words(n: int) -> str:
    """2026 -> 'ikki ming yigirma olti'; 1000 -> 'ming'; 0 -> 'nol'."""
    if n == 0:
        return "nol"
    out = []
    for size, name in SCALES:
        if n >= size:
            out += ([] if n // size == 1 and name == "ming" else [words(n // size)]) + [name]
            n %= size
    if n >= 100:
        out += ([] if n // 100 == 1 else [ONES[n // 100]]) + ["yuz"]  # "yuz yil", not "bir yuz yil"
        n %= 100
    out += [TENS[n // 10], ONES[n % 10]]
    return " ".join(w for w in out if w)


def ordinal(n: int) -> str:
    """5 -> 'beshinchi', 2 -> 'ikkinchi', 20 -> 'yigirmanchi'."""
    w = words(n)
    return w + ("nchi" if w[-1] in "aeiou" else "inchi")


def read_numbers(text: str) -> str:
    """'2026-yilda 47,9 % o'sdi, 1,000 kishi' -> 'ikki ming yigirma oltinchi yilda qirq yetti butun o'ndan to'qqiz foiz
    o'sdi, ming kishi'."""
    def say(m: re.Match) -> str:
        whole, frac, pct, word = m.groups()
        n = int(re.sub(r"[ ,]", "", whole))
        if word and not frac and not pct:  # "5-sinf": an ordinal; "5-da": a case ending, joined; "5-chi": ordinal already
            low = word.lower()
            return words(n) + word if low in ENDINGS else ordinal(n) if low in ORDINAL_ENDINGS else f"{ordinal(n)} {word}"
        said = words(n)
        if frac:
            said += f" butun {FRACTION[min(len(frac), 3)]} {words(int(frac[:3]))}"
        return said + (" foiz" if pct else "") + (word or "")

    text = re.sub(r"(\d)\s?[-–]\s?(?=\d)", r"\1 - ", text)  # a range, "1990-2000": a pause, not one glued word
    return NUMBER.sub(say, text)


def to_cyrillic(text: str) -> str:
    """Lower-case Cyrillic (MMS ignores case); digits and punctuation pass through."""
    return "".join(_word(p) if p.isalpha() or "'" in p else p
                   for p in re.split(r"([^\w']+)", APOSTROPHES.sub("'", text.lower())))
