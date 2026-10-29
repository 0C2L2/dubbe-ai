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


def test_each_speaker_their_own_voice_and_transcript(monkeypatch, tmp_path):
    cfg = config.load("ko", "en")
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
