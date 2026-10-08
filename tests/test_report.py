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
