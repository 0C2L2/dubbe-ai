import numpy as np

from dubbe import config, tts
from dubbe.report import transcript
from dubbe.speakers import cluster


def test_cluster_groups_voices_and_numbers_by_speech():
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=16), rng.normal(size=16)
    emb = [a + .05 * rng.normal(size=16) for _ in range(5)] + [b + .05 * rng.normal(size=16) for _ in range(3)]
    emb = np.array([e / np.linalg.norm(e) for e in emb])
    durs = [2.0, 2.0, 2.0, 0.5, 2.0, 3.0, 3.0, 3.0]  # sentence 3 is short: it joins its nearest speaker afterwards
    lab = cluster(emb, durs, 0.3)
    assert lab[:5] == [lab[0]] * 5 and lab[5:] == [lab[5]] * 3 and lab[0] != lab[5]
    assert lab[5] == 0  # B says 9 s, A 6.5 s: the main speaker is S1
    assert cluster(emb[:2], [2.0, 2.0], 0.3) == [0, 0]  # one person stays one speaker


CFG6 = {"split_min_words": 3, "split_min_s": 1.0, "split_gap": 0.2, "handover_min_s": 0.8, "handover_margin": 0.05,
        "merge_auto": 0.25, "merge_ask": 0.45}


def _words(*spec):  # (word, start, end)
    return [{"w": w, "start": a, "end": b} for w, a, b in spec]


def test_who_covers_most_or_nearest():
    from dubbe.diarize import who
    turns = [{"start": 0, "end": 5, "speaker": "A"}, {"start": 4.5, "end": 9, "speaker": "B"}, {"start": 9, "end": 9.5, "speaker": "C"}]
    assert who(turns, 4.0, 5.0) == "A" and who(turns, 4.8, 6.0) == "B"  # overlap: the one covering more of it
    assert who(turns, 9.6, 9.9) == "C"  # in a gap: the nearest turn


def test_bleed_words_join_the_sentence_speaker():
    from dubbe.speakers import assign
    turns = [{"start": 0, "end": 3.1, "speaker": "A"}, {"start": 3.1, "end": 6, "speaker": "B"}]
    ws = _words(("we", 0, .4), ("will", .45, .8), ("meet", .85, 1.3), ("again", 1.35, 2.0), ("at", 2.05, 2.3),
                ("four", 2.35, 2.9), ("today.", 3.0, 3.4))  # "today." bled into B's turn (0.4 s)
    segs, lab = assign([{"start": 0, "end": 3.4, "src_text": "we will meet again at four today."}], ws, turns, CFG6,
                       voice=lambda *a: None)
    assert lab == ["A"] and len(segs) == 1 and "speaker_flag" not in segs[0]  # too short to matter: no flag


def test_real_block_at_a_pause_is_split_off():
    from dubbe.speakers import assign
    turns = [{"start": 0, "end": 2.2, "speaker": "A"}, {"start": 2.4, "end": 5, "speaker": "B"}]
    ws = _words(("so", 0, .3), ("that", .35, .7), ("is", .75, 1.0), ("the", 1.05, 1.3), ("plan", 1.35, 2.1),
                ("yes", 2.5, 2.9), ("I", 2.95, 3.1), ("agree", 3.15, 3.7), ("completely.", 3.75, 4.6))
    segs, lab = assign([{"start": 0, "end": 4.6, "src_text": "x"}], ws, turns, CFG6, voice=lambda *a: None)
    assert lab == ["A", "B"] and [s["src_text"] for s in segs] == ["so that is the plan", "yes I agree completely."]


def test_handover_without_a_pause_needs_the_voice():
    from dubbe.speakers import assign
    turns = [{"start": 0, "end": 1.6, "speaker": "A"}, {"start": 1.6, "end": 3, "speaker": "B"}]
    ws = _words(("and", 0, .3), ("then", .35, .7), ("we", .75, 1.0), ("go", 1.05, 1.55),   # A
                ("to", 1.6, 1.8), ("the", 1.85, 2.0), ("park.", 2.05, 2.6))                  # B finishes it, no pause
    s = [{"start": 0, "end": 2.6, "src_text": "x"}]
    segs, lab = assign(s, ws, turns, CFG6, voice=lambda own, nb, span: True)   # voice: clearly B
    assert lab == ["A", "B"] and segs[1]["src_text"] == "to the park."
    segs, lab = assign(s, ws, turns, CFG6, voice=lambda own, nb, span: False)  # voice: not clear
    assert lab == ["A"] and segs[0]["speaker_flag"]                             # kept whole, checked in review


def test_same_voice_merged_close_voice_asked():
    from dubbe.speakers import name_speakers
    v = lambda *x: np.array(x) / np.linalg.norm(x)  # noqa: E731
    prof = {"A": v(1, 0, 0), "B": v(1, .3, 0), "C": v(0, 1, 0), "D": v(0, .65, .76)}  # A~B 0.04; C~D 0.35; rest > 0.8
    segs = [{"start": 4 * i, "end": 4 * i + 3.5} for i in range(6)]
    nums, maybe = name_speakers(segs, ["A", "B", "C", "A", "D", "C"], prof, CFG6)
    assert nums[0] == nums[1] == nums[3]           # A and B: one person
    assert nums[2] == nums[5] != nums[4]           # C and D stay two ...
    assert nums[2] in maybe[nums[4]]               # ... but the review asks


def test_turns_regrouped_by_voice_not_by_the_diarizer_labels():
    from dubbe.diarize import regroup
    rng = np.random.default_rng(1)
    a, b, c = (rng.normal(size=16) for _ in range(3))
    unit = lambda v: (v := v + .05 * rng.normal(size=16)) / np.linalg.norm(v)
    emb = np.array([unit(a), unit(b), unit(a), unit(c), unit(b), unit(a)])
    turns = [{"start": 4 * i, "end": 4 * i + 3.5, "speaker": "SPEAKER_00"} for i in range(6)]  # the diarizer merged all
    lab = [t["speaker"] for t in regroup(turns, emb, 0.35)]
    assert lab[0] == lab[2] == lab[5] and lab[1] == lab[4] and len(set(lab)) == 3  # three voices, three people
    assert lab[0] == "SPEAKER_00"                                                   # most speech = first speaker
    assert [t["speaker"] for t in regroup(turns[:1], emb[:1], 0.35)] == ["SPEAKER_00"]


def test_each_speaker_their_own_voice_and_transcript(monkeypatch, tmp_path):
    cfg = config.load("ko", "en")
    monkeypatch.setattr(tts, "MING_PY", tmp_path / "missing.exe")  # the voices before Ming / CosyVoice
    monkeypatch.setattr(tts, "COSYVOICE_PY", tmp_path / "missing.exe")
    monkeypatch.setattr(tts, "CHATTERBOX_PY", tmp_path)  # exists
    data = {"segments": [{"speaker": "S1", "tags": []}, {"speaker": "S2", "tags": []}],
            "speakers": {"S1": {"voice": "af_bella"}, "S2": {"voice": "video:S2"}}}
    assert tts.tts_cfg(data, cfg, tmp_path / "voice_prompt_S1.wav", "S1")["voice"] == "af_bella"
    assert tts.tts_cfg(data, cfg, tmp_path / "voice_prompt_S2.wav", "S2")["engine"] == "kokoro"  # no clone recording yet
    (tmp_path / "voice_prompt_S2.wav").write_bytes(b"RIFF")
    c = tts.tts_cfg(data, cfg, tmp_path / "voice_prompt_S2.wav", "S2")
    assert c["engine"] == "chatterbox" and c["voice"] == "video:S2"  # the speaker's own voice, cloned with consent
    segs = [{"start": 0, "end": 1, "speaker": "S1", "src_text": "Hello."}, {"start": 61, "end": 62, "speaker": "S2", "src_text": "Hi!"}]
    assert transcript(segs, "src_text", {"S1": {"name": "Walter"}, "S2": {"name": "Jesse"}}) == "[0:00.0] Walter: Hello.\n[1:01.0] Jesse: Hi!"
    assert transcript(segs[:1], "src_text", {}) == "[0:00.0] Hello."  # one speaker: no names
