import json

import numpy as np
import soundfile as sf

from dubbe import config, emotion, segment, tts

CFG = {"auto_tags": True, "emotion_min": 0.9, "sound_min": 0.3}
QUIET = {"laugh": 0.0, "sigh": 0.0, "gasp": 0.0, "cough": 0.0, "whisper": 0.0}


def test_tags_from_emotion_sounds_and_a_question_mark():
    sc = {"emotion": ("ang", 0.95), "sounds": {**QUIET, "laugh": 0.5, "sigh": 0.1}}
    assert emotion.tags_for(sc, "Why?", CFG) == ["question", "angry", "laugh"]
    assert emotion.tags_for({**sc, "emotion": ("hap", 0.8)}, "Fine.", CFG) == ["laugh"]  # not sure enough: no emotion


def test_heard_tags_go_on_every_sentence_but_the_reviewers(tmp_path, monkeypatch):
    sf.write(tmp_path / "audio.wav", np.zeros(4 * 16000, "float32"), 16000)
    segs = [{"id": 1, "start": 0, "end": 2, "src_text": "그래?"},
            {"id": 2, "start": 2, "end": 4, "src_text": "응.", "tags": ["slow"], "tags_edited": True}]
    (tmp_path / "segments.json").write_text(json.dumps({"segments": segs}), encoding="utf8")
    monkeypatch.setattr(emotion, "scores", lambda clips: [{"emotion": ("sad", 0.97), "sounds": QUIET} for _ in clips])
    emotion.run(None, tmp_path, CFG)
    a, b = json.loads((tmp_path / "segments.json").read_text(encoding="utf8"))["segments"]
    assert a["tags"] == a["auto_tags"] == ["question", "sad"] and b["tags"] == ["slow"] and "auto_tags" not in b


def test_reviewer_change_sticks_and_heard_tags_keep_the_voice(tmp_path, monkeypatch):
    s = {"tags": ["laugh"], "auto_tags": ["laugh"], "tgt_text": "Ha."}
    segment.edit(s, "", ["laugh"])  # saved without touching the tags
    assert not s.get("tags_edited")
    cfg = config.load("ko", "en")
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path)  # exists
    data = {"segments": [{"speaker": "S1", **s}], "speakers": {"S1": {"voice": "af_bella"}}}
    assert tts.tts_cfg(data, cfg)["voice"] == "af_bella"  # a heard [laugh] does not switch the whole video to Chatterbox
    segment.edit(data["segments"][0], "", ["laugh", "sad"])
    assert data["segments"][0]["tags_edited"] and tts.tts_cfg(data, cfg)["engine"] == "chatterbox"  # a person chose it
