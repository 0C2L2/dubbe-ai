import numpy as np

from dubbe.tags import not_performed, shape_audio, speed, text_for_tts


def test_question_tag_makes_a_question():
    assert text_for_tts("Is this the right road.", ["question"]) == "Is this the right road?"
    assert text_for_tts("Already a question?", ["question"]) == "Already a question?"
    assert text_for_tts("No tags.", []) == "No tags."


def test_speed_tags():
    assert speed(["slow"]) == 0.85 and speed(["fast", "soft"]) == 1.15 and speed([]) == 1.0


def test_soft_and_pause_shape_the_audio():
    a = np.full(100, 0.5, dtype="float32")
    out = shape_audio(a, 100, ["soft", "pause"])
    assert len(out) == 150 and out[0] == 0 and abs(out[-1] - 0.5 * 10 ** (-6 / 20)) < 1e-6


def test_vocal_tags_without_engine_support_are_reported():
    assert not_performed(["whisper", "slow", "laugh"], "kokoro") == ["laugh"]
    assert not_performed(["whisper", "sad", "laugh"], "mms") == ["laugh"]
    assert not_performed(["sad", "laugh", "cough"], "chatterbox") == []
    assert not_performed(["laugh", "question"], "chatterbox_ml") == ["laugh"]  # Korean voice makes no sounds (C19d)


def test_engine_tokens_go_in_front():
    assert text_for_tts("That is funny.", ["laugh", "slow"], "chatterbox") == "[laugh] That is funny."
    assert text_for_tts("Quiet now", ["whisper", "sigh", "question"], "chatterbox") == "[sigh] Quiet now?"
    assert text_for_tts("That is funny.", ["laugh"], "kokoro") == "That is funny."


def test_expression_tags_change_the_sound():
    sr = 16000
    t = np.arange(sr) / sr
    a = (0.5 * np.sin(2 * np.pi * 150 * t)).astype("float32")  # 1 s steady "voice" at 150 Hz

    def crossings(x):  # proportional to pitch for a sine
        return np.count_nonzero(np.diff(np.sign(x)))

    q = shape_audio(a, sr, ["question"])
    assert crossings(q[-1600:]) > 1.15 * crossings(q[:1600])  # the end is clearly higher than the start
    e, s = shape_audio(a, sr, ["excited"]), shape_audio(a, sr, ["sad"])
    assert len(e) < len(a) < len(s) and crossings(e[:sr // 2]) > crossings(a[:sr // 2]) > crossings(s[:sr // 2])
    buzz = sum(np.sin(2 * np.pi * 150 * k * t) / k for k in range(1, 30)).astype("float32") * .3  # voice-like: many harmonics
    w = shape_audio(buzz, sr, ["whisper"])
    period = sr // 150
    assert np.corrcoef(buzz[:-period], buzz[period:])[0, 1] > .9 > .3 > np.corrcoef(w[:-period], w[period:])[0, 1]  # no pitch left
    assert np.sqrt(np.mean(w ** 2)) > .5 * np.sqrt(np.mean(buzz ** 2))  # but about as loud
    assert np.abs(shape_audio(a * 1.9, sr, ["angry", "loud"])).max() <= .99  # never clipped
    assert w.dtype == q.dtype == np.float32
    assert len(shape_audio(np.zeros(0, "float32"), sr, ["whisper", "excited", "question"])) == 0  # "??": nothing to say


def test_korean_numbers_are_spoken_as_words():
    from dubbe.korean import read_numbers
    assert read_numbers("하나의 작업에 40초 동안, 5년 전 75초") == "하나의 작업에 사십초 동안, 오년 전 칠십오초"
    assert read_numbers("2016년에 12,345명이 3개씩") == "이천십육년에 만 이천삼백사십오명이 세개씩"  # 100+ stays Sino
    assert read_numbers("20살, 21살, 3시간, 1번째, 50%, 3.5") == "스무살, 스물한살, 세시간, 첫번째, 오십 퍼센트, 삼 점 오"
    assert text_for_tts("40초", [], "chatterbox_ml", "ko") == "사십초" and text_for_tts("40 seconds", [], "kokoro", "en") == "40 seconds"
