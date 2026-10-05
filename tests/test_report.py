from dubbe.config import load
from dubbe.report import flags

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
