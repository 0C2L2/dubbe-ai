from dubbe.segment import carry_over


def seg(i, a, b, **kw):
    return {"id": i, "start": a, "end": b, "tgt_text": None, "edited": False, **kw}


def test_edits_and_tags_follow_the_sentence_after_renumbering():
    old = [seg(1, 0, 4), seg(2, 5, 9, tgt_text="Fixed by a human.", edited=True, tags=["slow"])]
    new = [seg(1, 0, 2), seg(2, 2.1, 4), seg(3, 5.1, 8.9)]  # sentence 1 was split, sentence 2 is now number 3
    out = carry_over(old, new)
    assert out[2]["tgt_text"] == "Fixed by a human." and out[2]["edited"] and out[2]["tags"] == ["slow"]
    assert not out[0]["edited"] and "tags" not in out[0]


def test_merged_sentences_do_not_inherit_a_partial_edit():
    old = [seg(1, 0, 2, tgt_text="A.", edited=True), seg(2, 2.5, 4.5)]
    assert not carry_over(old, [seg(1, 0, 4.5)])[0]["edited"]
