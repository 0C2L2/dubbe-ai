"""Live Dubbing (beta): where pieces end, and what ffmpeg is allowed to read."""
from pathlib import Path

from dubbe import live


def test_a_piece_ends_at_a_pause_never_inside_a_word():
    from functools import partial
    cut = partial(live.cut, piece=10, most=20)
    speech = [(0, 4), (4.5, 9.6), (10.4, 13), (13.2, 19)]
    assert cut(speech, 19.5) == 10.0               # the first pause after 10 s: its middle
    assert cut([(0, 9), (9.2, 12)], 12.4) == 12.15  # nobody spoke on: just after the last word
    assert cut([(0, 9), (9.2, 12)], 12.1) is None   # maybe a breath: wait for more
    assert cut([(0, 25)], 21) == 20                      # nobody pauses: cut at 20 s
    assert cut([], 10.5) == 10.5                         # music or silence only
    assert live.cut([(0, 25)], 15) == 14 and live.DELAY == 20  # live: at most 14 s a piece, so 20 s behind covers it (C57)
    assert live.cut([(0, 5), (5.4, 30)], 14.2) == 5.2      # no pause after 7 s before 14: the last one before (C58)
    assert live.cut([(0, 2), (2.4, 30)], 14.2) == 14       # ... but not a piece shorter than 3.5 s
    assert live.cut([(0, 5), (5.4, 15), (15.4, 30)], 15.6) == 5.2  # the pause after 7 s comes too late (15.2 s)


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


def test_with_a_720p_and_a_480p_picture_each_viewer_gets_what_their_network_carries():
    cmd = live.ffmpeg_cmd([("https://v/720.m3u8", {}), ("https://v/480.m3u8", {}), ("https://v/a.m3u8", {})], True, Path("o"))
    assert cmd[cmd.index("-filter_complex") + 1].startswith("[2:a:0]") and "asplit=3[h0][h1][ap]" in cmd[cmd.index("-filter_complex") + 1]
    assert cmd[cmd.index("-var_stream_map") + 1] == "v:0,a:0 v:1,a:1"
    assert cmd.count("copy") == 1  # both pictures passed through, none re-encoded
    m = live.master([(4370, 1280, 720), (1569, 854, 480)])  # YouTube's bitrates, so a slow network drops to 480p
    assert "BANDWIDTH=4434000,RESOLUTION=1280x720\nvideo_0.m3u8" in m and "BANDWIDTH=1633000,RESOLUTION=854x480\nvideo_1.m3u8" in m


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


def test_what_whisper_makes_up_over_music_is_not_dubbed():
    """Seen on a YouTube live (C58): credits from Whisper's training data, a whole 30-s window, one word five times."""
    from types import SimpleNamespace as S
    segs = [S(start=0, end=30, text="Поехали дальше"), S(start=1, end=4, text=" Субтитры сделал DimaTorzok"),
            S(start=4, end=5, text="Корректор А.Кулакова"), S(start=5, end=6, text="Возвращение."),
            S(start=6, end=7, text="Возвращение."), S(start=7, end=9, text="Это очень близко!")]
    assert live.heard(segs, 12) == [(5, "Возвращение."), (7, "Это очень близко!")]
