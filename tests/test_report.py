from dubbe.config import load
from dubbe.report import cost, flags

CFG = load("ko", "en")


def seg(asr=0.95, mt=0.9, overflow=0.0):
    return {"asr_conf": asr, "mt_conf": mt, "overflow": overflow}


def test_clean_segment_not_flagged():
    assert flags(seg(), CFG) == []


def test_each_signal_flags_its_stage():
    assert flags(seg(asr=0.3), CFG) == ["low_asr"]
    assert flags(seg(mt=0.1), CFG) == ["low_mt"]
    assert flags(seg(overflow=1.2), CFG) == ["overflow"]


def test_missing_signals_are_ignored():
    # human-edited segments have no mt_conf; they must not be flagged for it
    assert flags({"asr_conf": None, "mt_conf": None, "overflow": None}, CFG) == []


def test_cost_maths():
    # 1 h of compute at 100 W and $0.20/kWh = $0.02; 30 min of video
    c = cost(3600, 1800, {"gpu_watts": 100, "electricity_usd_per_kwh": 0.2, "cloud_gpu_usd_per_hour": 0.5,
                         "elevenlabs_usd_per_min": [0.33, 2.2]})
    assert c["electricity"] == 0.02 and c["cloud_gpu"] == 0.5 and c["api_charges"] == 0
    assert c["per_video_minute"]["cloud_gpu"] == round(0.5 / 30, 4)
    assert c["elevenlabs_same_video"] == [9.9, 66.0]


def test_target_language_can_set_its_own_threshold():
    ko = load("en", "ko")  # Korean target uses min_mt_conf 0.5, English 0.6 (test-results C23)
    assert flags(seg(mt=0.55), ko) == [] and flags(seg(mt=0.55), CFG) == ["low_mt"]


def test_captions_coloured_by_speaker_in_srt_vtt_and_ass():
    from dubbe.report import ass, subtitles
    segs = [{"start": 0.0, "end": 1.5, "speaker": "S1", "src_text": "Hello."},
            {"start": 2.0, "end": 3.0, "speaker": "S2", "src_text": "Hi {there}!"}]
    spk = {"S1": {"name": "Walter"}, "S2": {"name": "Jesse"}}
    assert '<font color="#FFFF00">Hi {there}!</font>' in subtitles(segs, "src_text", speakers=spk)  # S2 yellow (BBC order)
    vtt = subtitles(segs, "src_text", vtt=True, speakers=spk)
    assert "::cue(.s2) { color: #FFFF00; }" in vtt and "<v.s1 Walter>Hello.</v>" in vtt
    a = ass(segs, "src_text", spk, "ko")
    assert "Style: S2,Malgun Gothic,58,&H0000FFFF" in a  # ASS colours are blue-green-red
    assert "Dialogue: 0,0:00:02.00,0:00:03.00,S2,Jesse,0,0,0,,Hi (there)!" in a  # braces would be ASS commands
    assert subtitles(segs[:1], "src_text", speakers=spk) == subtitles(segs[:1], "src_text")  # one speaker: no colours
