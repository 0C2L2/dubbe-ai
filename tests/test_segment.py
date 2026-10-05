from dubbe.config import load
from dubbe.segment import group

CFG = load("ko", "en")


def words(*spec):
    """spec: (text, start, end) tuples"""
    return [{"w": t, "start": s, "end": e} for t, s, e in spec]


def texts(sents):
    return [" ".join(w["w"] for w in s) for s in sents]


def test_sentence_ending_plus_short_pause_closes():
    w = words(("오늘은", 0, 0.5), ("배웁니다.", 0.6, 1.5), ("다음은", 1.9, 2.5), ("예제입니다.", 2.6, 3.6))
    assert texts(group(w, CFG)) == ["오늘은 배웁니다.", "다음은 예제입니다."]


def test_ending_without_pause_does_not_close():
    w = words(("바다", 0, 0.6), ("위에서", 0.65, 1.2), ("봅니다", 1.25, 2.0))
    assert len(group(w, CFG)) == 1


def test_long_pause_alone_closes():
    w = words(("first", 0, 0.6), ("part", 0.7, 1.4), ("second", 2.5, 3.2), ("part", 3.3, 4.0))
    assert texts(group(w, CFG)) == ["first part", "second part"]


def test_overlong_sentence_split_at_longest_pause():
    w = words(*[(f"w{i}", i * 1.0, i * 1.0 + 0.9) for i in range(10)],
              *[(f"v{i}", 10.5 + i * 1.0, 10.5 + i * 1.0 + 0.9) for i in range(10)])
    sents = group(w, CFG)
    assert len(sents) == 2 and sents[1][0]["w"] == "v0"


def test_tiny_fragment_merged_into_closer_neighbour():
    w = words(("long", 0, 1.0), ("sentence.", 1.1, 2.0), ("음.", 2.35, 2.6), ("next", 3.6, 4.5), ("one.", 4.6, 5.5))
    assert texts(group(w, CFG)) == ["long sentence. 음.", "next one."]


def test_every_word_kept_once_in_order():
    w = words(*[(f"w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(100)])
    flat = [x for s in group(w, CFG) for x in s]
    assert flat == w
