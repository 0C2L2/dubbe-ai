"""Live Dubbing (beta): where pieces end, and what ffmpeg is allowed to read."""
from pathlib import Path

from dubbe import live


def test_a_piece_ends_at_a_pause_never_inside_a_word():
    speech = [(0, 4), (4.5, 9.6), (10.4, 13), (13.2, 19)]
    assert live.cut(speech, 19.5) == 10.0               # the first pause after 10 s: its middle
    assert live.cut([(0, 9), (9.2, 12)], 12.4) == 12.15  # nobody spoke on: just after the last word
    assert live.cut([(0, 9), (9.2, 12)], 12.1) is None   # maybe a breath: wait for more
    assert live.cut([(0, 25)], 21) == 20                 # nobody pauses: cut at 20 s
    assert live.cut([], 10.5) == 10.5                    # music or silence only


def test_ffmpeg_reads_only_the_web_and_keeps_the_picture_as_it_is():
    cmd = live.ffmpeg_cmd([("https://example.org/live.m3u8", {"User-Agent": "x"})], True, Path("out"))
    allowed = cmd[cmd.index("-protocol_whitelist") + 1]
    assert "file" not in allowed and allowed.startswith("http")  # a link can never read a file on the server
    assert "-re" not in cmd and cmd[cmd.index("-c:v") + 1] == "copy"  # live: real time already; picture not re-encoded
    assert "-re" in live.ffmpeg_cmd([("https://example.org/v.mp4", {})], False, Path("out"))  # a video: at its own pace
    assert "first_pts=0" in cmd[cmd.index("-filter_complex") + 1]  # picture and dub start on the same clock


def test_a_youtube_live_comes_as_a_picture_stream_and_a_sound_stream():
    """YouTube serves a live stream only as separate picture and sound (C55): two inputs, each with its headers."""
    cmd = live.ffmpeg_cmd([("https://v.example/video.m3u8", {"A": "1"}), ("https://v.example/audio.m3u8", {"A": "1"})], True, Path("o"))
    assert [cmd[i + 1] for i, x in enumerate(cmd) if x == "-i"] == ["https://v.example/video.m3u8", "https://v.example/audio.m3u8"]
    assert cmd.count("-headers") == 2 and cmd.count("-protocol_whitelist") == 2
    assert cmd[cmd.index("-filter_complex") + 1].startswith("[1:a:0]") and "0:v:0?" in cmd  # sound from the second, picture from the first


def test_each_language_live_mode_dubs_into_has_its_fast_voices():
    assert live.voices("en")[0] == "af_heart" and "bm_george" in live.voices("en") and "built-in" not in live.voices("en")
    assert live.voices("kk") == [f"issai-{i}" for i in range(6)]          # Piper, the Kazakh offline voice
    assert live.voices("ko") == ["facebook/mms-tts-kor"] and live.voices("uz") == ["facebook/mms-tts-uzb-script_cyrillic"]


def test_mms_romanizes_with_one_uroman_not_one_per_sentence(monkeypatch):
    """The tokenizer loaded a new uroman for every Korean sentence: 4 s each, live Korean 1.3x slower than real time (C54)."""
    import sys
    import types
    from dubbe.tts import romanizer
    made = []
    fake = types.SimpleNamespace(Uroman=lambda: made.append(1) or types.SimpleNamespace(romanize_string=str.upper))
    monkeypatch.setitem(sys.modules, "uroman", fake)
    tok = types.SimpleNamespace(is_uroman=True)
    roman = romanizer(tok)
    assert [roman("an"), roman("nyeong")] == ["AN", "NYEONG"] and made == [1] and tok.is_uroman is False
    assert romanizer(types.SimpleNamespace(is_uroman=False))("x") == "x"  # Cyrillic Uzbek, Latin scripts: as they are
