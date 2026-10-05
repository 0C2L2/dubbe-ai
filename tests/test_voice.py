import numpy as np

from dubbe.voice import median_f0, pick, register

VOICES = {"am_michael": {"f0": 106, "register": "lower"}, "am_adam": {"f0": 116, "register": "lower"},
          "bm_george": {"f0": 126, "register": "lower"},
          "af_bella": {"f0": 123, "register": "higher"}, "bf_emma": {"f0": 173, "register": "higher"}}


def test_register_split():
    assert register(110, 122) == "lower" and register(140, 122) == "higher"


def test_pick_nearest_voice_in_same_register():
    assert pick(114, VOICES, 122) == "am_adam"
    assert pick(170, VOICES, 122) == "bf_emma"


def test_preset_label_beats_raw_pitch():
    # a 125 Hz (higher-register) speaker must not get bm_george (126 Hz) just because its pitch is nearest
    assert pick(125, VOICES, 122) == "af_bella"


def test_pick_falls_back_to_nearest_when_register_missing():
    assert pick(100, {"bf_emma": {"f0": 173, "register": "higher"}}, 122) == "bf_emma"


def test_median_f0_on_a_voiced_tone():
    sr = 16000
    t = np.arange(sr) / sr
    tone = sum(np.sin(2 * np.pi * 120 * k * t) / k for k in range(1, 6)).astype("float32")  # 120 Hz with harmonics
    assert abs(median_f0(tone, sr) - 120) < 10
