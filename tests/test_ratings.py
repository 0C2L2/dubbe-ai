from dubbe.ratings import summarize

SEGS = [{"id": 1, "flag": ["low_mt"]}, {"id": 2, "flag": []}, {"id": 3, "flag": ["low_asr"]}, {"id": 4, "flag": []}]


def r(rater, i, score, errors=(), hidden=True):
    return {"rater": rater, "id": i, "score": score, "errors": list(errors), "flags_hidden": hidden}


def test_flag_precision_and_recall_from_blind_ratings():
    rs = [r("A", 1, 30, ["wrong meaning"]), r("A", 2, 90), r("A", 3, 85), r("A", 4, 40)]
    s = summarize(rs, SEGS)
    # bad = {1, 4}; flagged = {1, 3}; hit = {1}
    assert s["blind"]["bad"] == 2 and s["blind"]["flag_precision"] == 0.5 and s["blind"]["flag_recall"] == 0.5


def test_ratings_seen_with_flags_do_not_count_for_flag_quality():
    s = summarize([r("A", 1, 10, hidden=False)], SEGS)
    assert s["blind"]["sentences"] == 0 and s["blind"]["flag_precision"] is None


def test_agreement_between_two_raters():
    rs = [r("A", 1, 20), r("B", 1, 30), r("A", 2, 90), r("B", 2, 30)]
    a = summarize(rs, SEGS)["agreement"]
    assert a["pairs"] == 2 and a["percent"] == 50.0
