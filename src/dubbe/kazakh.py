"""Kazakh numbers as spoken words for the Piper voice, which garbled digits ("1000" -> "біргімонға", "4,5" -> "түрк, бейс",
"5-сынып" -> "бейсініп"; heard back by Whisper turbo). num2words reads Kazakh ("kz"); ordinals and the case endings
written after a hyphen are added here. Subtitles keep the digits (only tags.text_for_tts calls this)."""
import re

from num2words import num2words

NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?: \d{3})+(?![.,]?\d)|\d+)(?:[.,](\d+))?(\s?%)?(?:-([^\W\d]+))?")
ORDINAL_ENDINGS = {"шы", "ші", "ншы", "нші", "ыншы", "інші"}  # "6-шы": already marked as an ordinal
IRREGULAR = {"жиырма": "жиырмасыншы", "қырық": "қырқыншы", "елу": "елуінші", "алпыс": "алпысыншы"}
# case and possessive endings written after a hyphen ("120-сы" = 120 of them, "5-те" = at five): joined, not an ordinal
ENDINGS = {"сы", "сі", "ы", "і", "да", "де", "та", "те", "ға", "ге", "қа", "ке", "на", "не", "а", "е", "ны", "ні", "ды", "ді",
           "ты", "ті", "дан", "ден", "тан", "тен", "нан", "нен", "мен", "бен", "пен", "дың", "дің", "тың", "тің", "ның", "нің"}
VOWELS, BACK = set("аәеиоөуұүыіэюя"), set("аоұыя")


def ordinal(n: int) -> str:
    """5 -> 'бесінші', 6 -> 'алтыншы', 2 -> 'екінші': -ыншы / -інші by the last vowel, -ншы / -нші after a vowel."""
    w = num2words(n, lang="kz")
    head, _, last = w.rpartition(" ")
    if last in IRREGULAR:  # 20 -> жиырмасыншы, not жиырманшы
        return f"{head} {IRREGULAR[last]}".strip()
    vowels = [c for c in w if c in VOWELS]
    back = bool(vowels) and vowels[-1] in BACK
    return w + ("" if w[-1] in VOWELS else ("ы" if back else "і")) + ("ншы" if back else "нші")


def read_numbers(text: str) -> str:
    """'2026-жылы 4,5% өсті, 120-сы' -> 'екі мың жиырма алтыншы жылы төрт бүтін бес пайыз өсті, жүз жиырмасы'."""
    def say(m: re.Match) -> str:
        whole, frac, pct, word = m.groups()
        n = int(whole.replace(" ", ""))
        if word and not frac and not pct:  # "5-сынып": ordinal; "120-сы": case ending, joined; "6-шы": ordinal already
            low = word.lower()
            return (num2words(n, lang="kz") + word if low in ENDINGS else ordinal(n) if low in ORDINAL_ENDINGS
                    else f"{ordinal(n)} {word}")
        said = num2words(float(f"{n}.{frac}"), lang="kz") if frac else num2words(n, lang="kz")
        return said + (" пайыз" if pct else "") + (word or "")

    text = re.sub(r"(\d)\s?[-–]\s?(?=\d)", r"\1 - ", text)  # a range: a pause, not one glued word
    return NUMBER.sub(say, text)
