import numpy as np

from dubbe import config, tts


def test_cut_tail_keeps_pauses_and_cuts_after_the_last_speech(monkeypatch):
    import faster_whisper.vad as vad
    sr = 16000
    # speech 0-0.5 s, a 0.8 s pause, speech 1.3-2.0 s, then 1 s of junk the VAD does not call speech
    monkeypatch.setattr(vad, "get_speech_timestamps", lambda x, o: [{"start": 0, "end": 8000}, {"start": 20800, "end": 32000}])
    assert len(tts.cut_tail(np.zeros(3 * sr, "float32"), sr)) == int((2.0 + .15) * sr)  # after the LAST speech
    monkeypatch.setattr(vad, "get_speech_timestamps", lambda x, o: [])
    assert len(tts.cut_tail(np.zeros(sr, "float32"), sr)) == sr  # no speech found: leave it alone


def test_korean_voice_falls_back_to_mms_without_chatterbox(monkeypatch, tmp_path):
    cfg = config.load("en", "ko")
    data = {"segments": [], "speakers": {"S1": {"voice": "built-in"}}}
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path / "missing.exe")
    assert tts.tts_cfg(data, cfg)["engine"] == "mms" and tts.tts_cfg(data, cfg)["voice"] == "facebook/mms-tts-kor"
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path)  # exists
    assert tts.tts_cfg(data, cfg)["engine"] == "chatterbox_ml" and tts.tts_cfg(data, cfg)["voice"] == "built-in"


def test_english_question_switches_to_the_expressive_voice(monkeypatch, tmp_path):
    cfg = config.load("ko", "en")
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path)  # exists
    asked = {"segments": [{"tags": ["question"]}], "speakers": {"S1": {"voice": "af_heart"}}}
    plain = {"segments": [{"tags": ["slow"]}], "speakers": {"S1": {"voice": "af_heart"}}}
    assert tts.tts_cfg(asked, cfg)["engine"] == "chatterbox" and tts.tts_cfg(plain, cfg)["voice"] == "af_heart"
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path / "missing.exe")
    assert tts.tts_cfg(asked, cfg)["engine"] == "kokoro"  # no environment: Kokoro with DUBBE's glide only


def test_clone_speaks_only_with_its_recording(monkeypatch, tmp_path):
    from dubbe.web.clones import cer
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path)  # exists
    data = {"segments": [], "speakers": {"S1": {"voice": "clone:7"}}}
    prompt = tmp_path / "voice_prompt.wav"
    assert tts.tts_cfg(data, config.load("ko", "en"), prompt)["voice"] == "af_heart"  # no recording for this job: default voice
    prompt.write_bytes(b"RIFF")
    c = tts.tts_cfg(data, config.load("ko", "en"), prompt)
    assert c["engine"] == "chatterbox" and c["voice"] == "clone:7" and c["prompt"] == str(prompt)
    assert tts.tts_cfg(data, config.load("en", "ko"), prompt)["engine"] == "chatterbox_ml"  # Korean
    assert cer("Hello, world.", "hello world") == 0 and cer("abc", "xyz") == 1  # the consent check's comparison


def test_english_preset_speaks_korean_through_chatterbox_with_its_reference(monkeypatch, tmp_path):
    cfg = config.load("en", "ko")
    cfg["tgt"]["tts"]["voices"]["af_heart"] = {"f0": 150, "register": "higher", "prompt": "kokoro"}
    data = {"segments": [], "speakers": {"S1": {"voice": "af_heart"}}}
    monkeypatch.setattr(tts, "preset_prompt", lambda v: tmp_path / f"{v}.wav")
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path)  # exists
    c = tts.tts_cfg(data, cfg)
    assert c["engine"] == "chatterbox_ml" and c["voice"] == "af_heart" and c["prompt"].endswith("af_heart.wav")
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path / "missing.exe")
    assert tts.tts_cfg(data, cfg)["engine"] == "mms"  # without Chatterbox: the Korean fallback voice


def test_every_language_loads_with_its_codes_and_voices():
    import yaml
    from pathlib import Path
    langs = [k for k in yaml.safe_load((Path(config.__file__).parent / "languages.yaml").read_text(encoding="utf8")) if k != "defaults"]
    assert len(langs) == 22 and "no" in langs and "he" not in langs  # a bare `no:` would be YAML's false; Hebrew failed (C25)
    for code in langs:
        tgt = config.load("ko" if code == "en" else "en", code)["tgt"]
        assert tgt["tts"]["engine"] in tts.ENGINES and isinstance(tgt["whisper"], str) and "_" in tgt["nllb"]
        assert tgt["tts"]["voice"] in tgt["tts"]["voices"] or code == "en"  # the default voice is one of its voices
    fr = config.load("en", "fr")["tgt"]["tts"]
    assert "built-in" not in fr["voices"] and fr["voices"][fr["voice"]]["prompt"]  # its built-in voice failed: a preset speaks


def test_babble_after_the_sentence_is_cut_but_a_misheard_word_is_not():
    said = "Où as-tu mis les vieux dossiers de l'année dernière ?"
    heard = [("Où", .3), (" as-tu", .6), (" mis", .8), (" les", .9), (" vieux", 1.1), (" dossiers", 1.5), (" de", 1.6),
             (" l'année", 1.9), (" dernière", 2.3), (" ?", 2.3), (" N'enfin,", 2.8), (" s'y", 3.0), (" mitrait.", 3.4), (" Et", 3.6),
             (" suri.", 3.9)]  # French dub, bf_alice (test-results C25)
    assert tts.babble_cut(heard, said) == 2.3
    assert tts.babble_cut([("Merci", .4), (" beaucoup", .9), (" Paula.", 1.3)], "Merci beaucoup pour l'offre.") is None
    assert tts.babble_cut(heard[:10], said) is None  # nothing after the sentence
    assert tts.babble_cut([("[laugh]", .2), ("Ha", .5)], "[laugh] Ha") is None
