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
    """C10: match each speaker's dub voice to their pitch register - a preset voice, never a clone of the speaker.
    A voice chosen when the dub was started (cfg["voice"]: a preset, or the user's own consented clone) is the main
    speaker's (S1); a voice set later in the review editor (override) wins. Different speakers get different presets
    while the library has enough of them. Speakers come from the speakers stage (C7); without it everything is S1."""
    data = read_json(work / "segments.json")
    segs = data["segments"]
    wav = work / "vocals.wav" if (work / "vocals.wav").exists() else work / "audio.wav"  # voice stem: music skews pitch
    audio, sr = sf.read(wav, dtype="float32")
    audio = audio.mean(1) if audio.ndim > 1 else audio
    for s in segs:
        s.setdefault("speaker", "S1")
    groups: dict[str, list] = {}
    for s in segs:
        groups.setdefault(s["speaker"], []).append(audio[int(s["start"] * sr):int(s["end"] * sr)])
    tts = cfg["tgt"]["tts"]
    old_all, out, used = data.get("speakers", {}), {}, set()
    for sp in sorted(groups, key=lambda k: -sum(len(c) for c in groups[k])) or ["S1"]:  # the main speaker picks first
        old = old_all.get(sp, {})
        f0 = median_f0(np.concatenate(groups[sp]) if groups.get(sp) else audio, sr)
        voices = tts.get("voices") or {tts["voice"]: {"f0": f0}}  # no library: the one configured voice
        chosen = old["voice"] if old.get("override") else cfg.get("voice") if sp == "S1" else None
        voice = chosen or pick(f0, {v: p for v, p in voices.items() if v not in used} or voices, cfg["register_split_hz"])
        used.add(voice)
        out[sp] = {**old, "name": old.get("name") or f"Speaker {sp[1:]}", "median_f0": round(f0, 1),
                   "register": register(f0, cfg["register_split_hz"]), "voice": voice, "override": bool(chosen)}
    data["speakers"] = out
    write_json(work / "segments.json", data)
