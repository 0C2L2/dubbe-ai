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
    cmd = live.ffmpeg_cmd("https://example.org/live.m3u8", True, {"User-Agent": "x"}, Path("out"))
    allowed = cmd[cmd.index("-protocol_whitelist") + 1]
    assert "file" not in allowed and allowed.startswith("http")  # a link can never read a file on the server
    assert "-re" not in cmd and cmd[cmd.index("-c:v") + 1] == "copy"  # live: real time already; picture not re-encoded
    assert "-re" in live.ffmpeg_cmd("https://example.org/v.mp4", False, {}, Path("out"))  # a video: played at its own pace
    assert "first_pts=0" in cmd[cmd.index("-filter_complex") + 1]  # picture and dub start on the same clock
