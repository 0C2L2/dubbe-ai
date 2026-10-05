from pathlib import Path

import numpy as np
import soundfile as sf

from . import read_json, write_json


def median_f0(x: np.ndarray, sr: int) -> float:
    """Median pitch (Hz) over the louder half of the frames (= voiced speech).
    torchaudio's detector reads low in absolute terms, but speakers and preset voices are measured
    with the same function, so comparisons hold (register split calibrated on FLEURS: 95 %)."""
    import torch
    import torchaudio.functional as F

    f = F.detect_pitch_frequency(torch.from_numpy(np.ascontiguousarray(x, dtype="float32"))[None], sr,
                                 freq_low=60, freq_high=400)[0].numpy()
    hop = len(x) / len(f)
    rms = np.array([np.sqrt(np.mean(x[int(i * hop):int((i + 1) * hop)] ** 2) + 1e-12) for i in range(len(f))])
    return float(np.median(f[rms > np.median(rms)]))


def register(f0: float, split_hz: float) -> str:
    return "lower" if f0 < split_hz else "higher"


def pick(f0: float, voices: dict[str, dict], split_hz: float) -> str:
    """Preset voice in the speaker's register with the nearest pitch; nearest overall if the library
    has no voice in that register. A preset's register is its own label (pitch alone crosses perceived
    voice type: the low male preset bm_george measures above two female presets)."""
    same = {v: p for v, p in voices.items() if p.get("register", register(p["f0"], split_hz)) == register(f0, split_hz)}
    pool = same or voices
    return min(pool, key=lambda v: abs(pool[v]["f0"] - f0))


def run(video: Path, work: Path, cfg: dict) -> None:
    """C10: match the dub voice to the speaker's pitch register - a preset voice, never a clone.
    Single speaker for now (S1); per-speaker profiles come with diarization (C7)."""
    data = read_json(work / "segments.json")
    old = data.get("speakers", {}).get("S1", {})
    wav = work / "vocals.wav" if (work / "vocals.wav").exists() else work / "audio.wav"  # voice stem: music skews pitch
    audio, sr = sf.read(wav, dtype="float32")
    speech = [audio[int(s["start"] * sr):int(s["end"] * sr)] for s in data["segments"]]
    f0 = median_f0(np.concatenate(speech) if speech else audio, sr)

    tts = cfg["tgt"]["tts"]
    voices = tts.get("voices") or {tts["voice"]: {"f0": f0}}  # no library: the one configured voice
    voice = old["voice"] if old.get("override") else pick(f0, voices, cfg["register_split_hz"])
    data["speakers"] = {"S1": {"median_f0": round(f0, 1), "register": register(f0, cfg["register_split_hz"]),
                               "voice": voice, "override": bool(old.get("override"))}}
    for s in data["segments"]:
        s["speaker"] = "S1"
    write_json(work / "segments.json", data)
