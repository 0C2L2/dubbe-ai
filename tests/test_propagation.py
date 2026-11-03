from dubbe.propagation import align, blame, cer, wer


def test_cer_ignores_spaces_and_punctuation():
    assert cer("하위 문화를", "하위문화를.") == 0
    assert round(cer("사위문화", "하위문화"), 2) == 0.25


def test_wer():
    assert wer("the cat sat", "The cat sat!") == 0
    assert round(wer("the dog sat", "the cat sat"), 2) == 0.33


def test_align_maps_our_segments_into_reference_sentences():
    ref = [{"start": 0, "end": 5, "src": "a", "tgt": "A"}, {"start": 6, "end": 12, "src": "b", "tgt": "B"}]
    segs = [{"id": 1, "start": 0.5, "end": 4, "src_text": "x", "tgt_text": "X"},
            {"id": 2, "start": 6.2, "end": 8, "src_text": "y", "tgt_text": "Y"},
            {"id": 3, "start": 8.5, "end": 11.5, "src_text": "z", "tgt_text": "Z"}]
    a = align(ref, segs)
    assert a[0]["ids"] == [1] and a[1]["ids"] == [2, 3] and a[1]["tgt"] == "Y Z"


def test_blame():
    assert blame(0.30, 30, 70) == "ASR"           # good input fixes it -> recognition was the problem
    assert blame(0.02, 35, 38) == "translation"   # even with the right transcript the translation is poor
    assert blame(0.02, 80, 82) == "ok"
