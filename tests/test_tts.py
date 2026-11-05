from pathlib import Path

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
    monkeypatch.setattr(tts, "MING_PY", tmp_path / "missing.exe")  # the voices before Ming / CosyVoice
    monkeypatch.setattr(tts, "COSYVOICE_PY", tmp_path / "missing.exe")
    cfg = config.load("en", "ko")
    data = {"segments": [], "speakers": {"S1": {"voice": "built-in"}}}
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path / "missing.exe")
    assert tts.tts_cfg(data, cfg)["engine"] == "mms" and tts.tts_cfg(data, cfg)["voice"] == "facebook/mms-tts-kor"
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path)  # exists
    assert tts.tts_cfg(data, cfg)["engine"] == "chatterbox_ml" and tts.tts_cfg(data, cfg)["voice"] == "built-in"


def test_english_question_switches_to_the_expressive_voice(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "MING_PY", tmp_path / "missing.exe")  # the voices before Ming / CosyVoice
    monkeypatch.setattr(tts, "COSYVOICE_PY", tmp_path / "missing.exe")
    cfg = config.load("ko", "en")
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path)  # exists
    asked = {"segments": [{"tags": ["question"]}], "speakers": {"S1": {"voice": "af_heart"}}}
    plain = {"segments": [{"tags": ["slow"]}], "speakers": {"S1": {"voice": "af_heart"}}}
    assert tts.tts_cfg(asked, cfg)["engine"] == "chatterbox" and tts.tts_cfg(plain, cfg)["voice"] == "af_heart"
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path / "missing.exe")
    assert tts.tts_cfg(asked, cfg)["engine"] == "kokoro"  # no environment: Kokoro with DUBBE's glide only


def test_clone_speaks_only_with_its_recording(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "MING_PY", tmp_path / "missing.exe")  # the voices before Ming / CosyVoice
    monkeypatch.setattr(tts, "COSYVOICE_PY", tmp_path / "missing.exe")
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
    monkeypatch.setattr(tts, "MING_PY", tmp_path / "missing.exe")  # the voices before Ming / CosyVoice
    monkeypatch.setattr(tts, "COSYVOICE_PY", tmp_path / "missing.exe")
    cfg = config.load("en", "ko")
    cfg["tgt"]["tts"]["voices"]["af_heart"] = {"f0": 150, "register": "higher", "prompt": "kokoro"}
    data = {"segments": [], "speakers": {"S1": {"voice": "af_heart"}}}
    monkeypatch.setattr(tts, "preset_prompt", lambda v: tmp_path / f"{v}.wav")
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path)  # exists
    c = tts.tts_cfg(data, cfg)
    assert c["engine"] == "chatterbox_ml" and c["voice"] == "af_heart" and c["prompt"].endswith("af_heart.wav")
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path / "missing.exe")
    assert tts.tts_cfg(data, cfg)["engine"] == "mms"  # without Chatterbox: the Korean fallback voice


def test_korean_and_english_speak_from_a_recording(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "MING_PY", tmp_path)  # exists
    monkeypatch.setattr(tts, "COSYVOICE_PY", tmp_path)
    monkeypatch.setattr(tts, "preset_prompt", lambda v: tmp_path / f"{v}.wav")
    data = {"segments": [{"tags": ["question"]}], "speakers": {"S1": {"voice": "am_michael"}, "S2": {"voice": "clone:7"}}}
    prompt = tmp_path / "voice_prompt.wav"
    prompt.write_bytes(b"RIFF")
    for engine in tts.PROMPTED:  # Ming (the setting now) and CosyVoice
        for src, tgt in [("ko", "en"), ("en", "ko")]:
            cfg = config.load(src, tgt)
            cfg["tgt"]["tts"].update(engine=engine, clone=engine)
            c = tts.tts_cfg(data, cfg)
            assert c["engine"] == engine and c["voice"] == "am_michael" and c["prompt"].endswith("am_michael.wav")
            c = tts.tts_cfg(data, cfg, prompt, "S2")
            assert c["engine"] == engine and c["prompt"] == str(prompt)  # a consented clone, same engine
    monkeypatch.setattr(tts, "COSYVOICE_PY", tmp_path / "missing.exe")  # Ming hands lines to CosyVoice
    monkeypatch.setattr(tts, "MING_PY", tmp_path / "missing.exe")
    plain = {"segments": [{"tags": []}], "speakers": {"S1": {"voice": "am_michael"}}}
    assert tts.tts_cfg(plain, config.load("ko", "en"))["engine"] == "kokoro"  # no base environment: the earlier voices


def test_every_language_loads_with_its_codes_and_voices():
    import yaml
    from pathlib import Path
    langs = [k for k in yaml.safe_load((Path(config.__file__).parent / "languages.yaml").read_text(encoding="utf8")) if k != "defaults"]
    assert len(langs) == 24 and "no" in langs and "he" not in langs  # a bare `no:` would be YAML's false; Hebrew failed (C25)
    assert {"uz", "kk"} <= set(langs)  # free Central Asian voices (C43)
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


def test_ming_hands_cosyvoice_what_it_cannot_say(monkeypatch, tmp_path):
    from dubbe.tags import text_for_tts
    monkeypatch.setattr(tts, "COSYVOICE_PY", tmp_path)  # exists
    calls = []

    def speak(texts, cfg):
        calls.append((cfg["engine"], texts))
        return iter([(np.full(4, len(calls), "float32"), 44100 if cfg["engine"] == "ming" else 24000)] * len(texts))
    monkeypatch.setattr(tts, "_prompted", speak)
    errs = iter([[0.0, 0.3, 0.0], [0.1]])  # Whisper: Ming's 2nd sentence 30 % off; CosyVoice's take of it 10 %
    monkeypatch.setattr(tts, "word_errors", lambda clips, texts, lang: next(errs))
    texts = [text_for_tts("Hi.", [], "ming"), text_for_tts("Oh no.", ["sad"], "ming"),
             text_for_tts("I am sorry.", ["sympathetic"], "ming")]
    out = list(tts._ming(texts, {"engine": "ming", "prompt": "p.wav"}))
    assert calls == [("ming", ["Hi.", "悲伤<|endofprompt|>Oh no."]),  # Ming: what it can do
                     ("cosyvoice", ["Please speak gently and warmly, with deep sympathy.<|endofprompt|>I am sorry."]),  # beyond Ming
                     ("cosyvoice", ["Please speak sadly, in a low and slow voice.<|endofprompt|>Oh no."])]  # off: again, same emotion
    assert [round(float(c[0][0])) for c in out] == [1, 3, 2] and {c[1] for c in out} == {44100}  # better take, one rate

    calls.clear()
    errs = iter([[0.3, 0.0], [0.4]])  # Korean: CosyVoice speaks plain lines and is checked too; a worse retry keeps the first
    texts = [text_for_tts("안녕.", [], "ming"), text_for_tts("싫어.", ["angry"], "ming")]
    out = list(tts._ming(texts, {"engine": "ming", "prompt": "p.wav", "plain": "cosyvoice"}))
    assert calls == [("ming", ["愤怒<|endofprompt|>싫어."]), ("cosyvoice", ["안녕."]), ("cosyvoice", ["안녕."])]
    assert [round(float(c[0][0])) for c in out] == [2, 1]

    voices = []  # two speakers in one call: every part of the hybrid keeps each sentence's own recording
    monkeypatch.setattr(tts, "_prompted", lambda texts, cfg: voices.append(cfg["prompts"]) or speak(texts, cfg))
    errs = iter([[0.0, 0.0]])
    list(tts._ming([text_for_tts("안녕.", [], "ming"), text_for_tts("싫어.", ["angry"], "ming")],
                   {"engine": "ming", "prompts": ["a.wav", "b.wav"], "plain": "cosyvoice"}))
    assert voices == [["b.wav"], ["a.wav"]]


def test_uzbek_speaks_with_navoiy_and_kazakh_never_clones(monkeypatch, tmp_path):
    import json
    import subprocess
    import soundfile as sf
    sent = {}

    def run(cmd, input, **kw):  # the worker: write a wav per item, as cosyvoice_worker.py would
        sent.update(cmd=cmd, job=json.loads(input))
        for it in sent["job"]["items"]:
            sf.write(it["out"], np.zeros(10, "float32"), 24000)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(tts.subprocess, "run", run)
    from dubbe.tags import text_for_tts
    texts = [text_for_tts("Salom.", [], "navoiy", "uz"), text_for_tts("Yo'q.", ["sad"], "navoiy", "uz")]
    list(tts._prompted(texts, {"engine": "navoiy", "prompt": "p.wav"}))
    items = sent["job"]["items"]
    assert sent["cmd"][-1].endswith("cosyvoice_worker.py") and sent["job"]["llm"] == list(tts.NAVOIY_LLM)
    assert sent["job"]["model"] == tts.NAVOIY_MODEL and items[0]["instruct"].startswith("Speak in a calm")  # plain: calm
    assert items[1]["text"] == "Yo'q." and items[1]["instruct"].startswith("Speak in a sad")

    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path)  # exists: before the fix this sent a Kazakh clone to tts["clone"]
    prompt = tmp_path / "voice_prompt.wav"
    prompt.write_bytes(b"RIFF")
    data = {"segments": [{"tags": []}], "speakers": {"S1": {"voice": "clone:7"}}}
    c = tts.tts_cfg(data, config.load("en", "kk"), prompt)
    assert c["engine"] == "piper" and c["voice"] == "issai-0"  # no voice speaks Kazakh from a recording: the default


def test_redub_speaks_only_changed_sentences(monkeypatch, tmp_path):
    """A 20-minute video and one sentence fixed: one sentence is spoken again, not all of them (C49)."""
    import json
    monkeypatch.setattr(tts, "MING_PY", tmp_path)  # exists
    monkeypatch.setattr(tts, "COSYVOICE_PY", tmp_path)
    monkeypatch.setattr(tts, "preset_prompt", lambda v: tmp_path / f"{v}.wav")
    spoken = []
    monkeypatch.setitem(tts.ENGINES, "ming", lambda texts, c: spoken.append((texts, c["seeds"])) or
                        iter([(np.full(800, .5, "float32"), 16000)] * len(texts)))
    segs = [{"id": i, "speaker": "S1", "tgt_text": f"Line {i}.", "tags": []} for i in (1, 2, 3)]
    (tmp_path / "segments.json").write_text(json.dumps({"segments": segs, "speakers": {"S1": {"voice": "am_michael"}}}))
    cfg = config.load("ko", "en")
    redub = lambda: tts.run(tmp_path / "v.mp4", tmp_path, cfg) or json.loads((tmp_path / "segments.json").read_text())  # noqa: E731

    redub()
    assert [len(t) for t, _ in spoken] == [3]  # first dub: every sentence
    spoken.clear()
    data = redub()
    assert spoken == []  # nothing changed: every clip kept
    data["segments"][1]["tgt_text"] = "Line two, fixed."
    data["segments"][2]["take"] = 1  # "Try again"
    (tmp_path / "segments.json").write_text(json.dumps(data))
    data = redub()
    assert [(len(t), seeds) for t, seeds in spoken] == [(2, [0, 1])]  # the fixed one and the retake, with its own seed
    assert data["spoken"] == [2, 3]  # what this run spoke: a library clone's use counts only these
    spoken.clear()
    data["speakers"]["S1"]["voice"] = "af_bella"  # a new voice for the speaker: all their sentences again
    (tmp_path / "segments.json").write_text(json.dumps(data))
    redub()
    assert [len(t) for t, _ in spoken] == [3]


def test_every_speaker_is_spoken_in_one_call(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "MING_PY", tmp_path)  # exists
    monkeypatch.setattr(tts, "COSYVOICE_PY", tmp_path)
    monkeypatch.setattr(tts, "preset_prompt", lambda v: tmp_path / f"{v}.wav")
    calls = []
    monkeypatch.setitem(tts.ENGINES, "ming", lambda texts, c: calls.append(c["prompts"]) or
                        iter([(np.zeros(2, "float32"), 44100)] * len(texts)))
    data = {"segments": [{"id": 1, "speaker": "S1"}, {"id": 2, "speaker": "S2"}, {"id": 3, "speaker": "S1"}],
            "speakers": {"S1": {"voice": "am_michael"}, "S2": {"voice": "af_bella"}}}
    out = list(tts.synth(data, config.load("ko", "en"), tmp_path, [(s, f"Line {s['id']}.") for s in data["segments"]]))
    a, b = str(tmp_path / "am_michael.wav"), str(tmp_path / "af_bella.wav")
    assert calls == [[a, a, b]]  # one load for both speakers (KOR news: 5 speakers were 5 loads)
    assert [(s["id"], sp, t["voice"]) for s, _, _, t, sp in out] == [(1, "S1", "am_michael"), (3, "S1", "am_michael"),
                                                                    (2, "S2", "af_bella")]


def test_every_sentence_is_spoken_at_one_level():
    """One speaker's clips came out up to 12 dB apart (C50): each is set to LEVEL_DB, pauses not counted."""
    sr = 16000
    tone = np.sin(2 * np.pi * 150 * np.arange(sr) / sr).astype("float32")
    quiet, loud = tone * .05, tone * .2  # 12 dB apart
    with_pause = np.concatenate([np.zeros(sr, "float32"), quiet])
    for x in (quiet, loud, with_pause):
        assert abs(tts.speech_db(tts.level(x, sr), sr) - tts.LEVEL_DB) < .1
    assert not tts.level(np.zeros(sr, "float32"), sr).any() and tts.level(quiet, sr).dtype == np.float32


def test_ming_hears_the_reference_itself_when_it_knows_what_it_says(monkeypatch, tmp_path):
    """Without a transcript Ming drops the reference's sound and keeps only a speaker fingerprint (C62)."""
    import json
    import subprocess
    import soundfile as sf
    sent = {}

    def run(cmd, input, **kw):
        sent["items"] = json.loads(input)["items"]
        for it in sent["items"]:
            sf.write(it["out"], np.zeros(10, "float32"), 44100)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(tts.subprocess, "run", run)
    monkeypatch.setattr(tts, "PROMPTS", tmp_path)
    (tmp_path / "af_test.wav").write_bytes(b"RIFF")  # already recorded: no Kokoro needed
    preset = tts.preset_prompt("af_test")
    assert tts.prompt_text(preset, "en") == tts.PROMPT_TEXT  # a preset says PROMPT_TEXT, in English
    assert tts.prompt_text(preset, "ko") is None  # an English recording for Korean: worse words (C62), fingerprint only
    clone = tmp_path / "voice_prompt_S2.wav"
    clone.write_bytes(b"RIFF")
    list(tts._prompted(["Hi.", "Bye."], {"engine": "ming", "prompts": [str(preset), str(clone)]}))
    assert sent["items"][0]["prompt_text"] == tts.PROMPT_TEXT  # English dub (lang unset = English)
    assert sent["items"][1]["prompt_text"] is None  # a clone made before C62: no text, fingerprint only
    clone.with_suffix(".txt").write_text("ko\n안녕하세요", encoding="utf8")
    list(tts._prompted(["안녕."], {"engine": "ming", "lang": "ko", "prompt": str(clone)}))
    assert sent["items"][0]["prompt_text"] == "안녕하세요"  # a Korean clone in a Korean dub
