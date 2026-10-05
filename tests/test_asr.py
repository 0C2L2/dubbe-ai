import numpy as np

from dubbe.asr import drop_silent

SR = 16000


def test_words_over_silence_are_dropped():
    audio = np.zeros(4 * SR, dtype="float32")
    audio[:SR] = 0.1 * np.sin(np.arange(SR) / 5)  # speech-like sound in the first second only
    words = [{"w": "real", "start": 0.2, "end": 0.8}, {"w": "invented", "start": 2.0, "end": 3.5}]
    assert [w["w"] for w in drop_silent(words, audio, SR, -60)] == ["real"]


def test_zero_length_word_does_not_crash():
    audio = np.full(SR, 0.1, dtype="float32")
    assert len(drop_silent([{"w": "x", "start": 0.5, "end": 0.5}], audio, SR, -60)) == 1
