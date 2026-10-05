from dubbe.shorten import pick

ALTS = [{"text": "Studies even show that a short break can reset this resource.", "conf": 0.60},
        {"text": "Studies show a short break can reset it.", "conf": 0.55},
        {"text": "A break resets it.", "conf": 0.20}]


def test_picks_shortest_with_good_enough_confidence():
    assert pick(ALTS, ALTS[0]["text"], 0.85) == "Studies show a short break can reset it."


def test_low_confidence_alternative_is_never_used():
    assert pick(ALTS, ALTS[0]["text"], 0.99) is None


def test_nothing_shorter_than_current():
    assert pick(ALTS, "Short.", 0.5) is None
