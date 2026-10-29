"""Korean text as it should be spoken: digits written out in words, because the Korean voices misread them
(Chatterbox Multilingual garbled "40초" and "75초", MMS dropped "2016년" - test-results C9b). Subtitles keep the digits."""
import re

from num2words import num2words

# counters that take native Korean numbers (세 개, 두 명, 세 시, 스무 살); every other number is Sino-Korean
# (사십 초, 이천십육 년, 삼 퍼센트). Longer counters first so "시간" wins over "시". Ambiguous ones (대, 장) are left Sino.
NATIVE = ["번째", "시간", "가지", "군데", "사람", "개", "명", "시", "살", "번", "마리", "잔", "권", "달"]
ONES = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
COUNTER = re.compile(r"\s?(?:" + "|".join(NATIVE) + ")")


def native(n: int) -> str:
    return "스무" if n == 20 else TENS[n // 10] + ONES[n % 10]


def read_numbers(text: str) -> str:
    """'40초 동안, 5년 전에 3개' -> '사십초 동안, 오년 전에 세개'; '50%' -> '오십 퍼센트'."""
    text = re.sub(r"(\d)\s?%", r"\1 퍼센트", text)

    def say(m: re.Match) -> str:
        raw = m.group().replace(",", "")
        if "." in raw:
            return num2words(float(raw), lang="ko")
        n = int(raw)
        counter = COUNTER.match(text, m.end())
        if counter and 0 < n < 100:
            return "첫" if n == 1 and counter.group().strip() == "번째" else native(n)
        return num2words(n, lang="ko")

    return NUMBER.sub(say, text)
