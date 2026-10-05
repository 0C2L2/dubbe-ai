from pathlib import Path

import numpy as np
import soundfile as sf

from . import db, ffmpeg, read_json, video_duration, write_json


def place(segs: list[dict], total: float, max_stretch: float, max_slow: float = 1.0) -> list[dict]:
    """Decide speed-up, video slow-down and start time per segment (known hard part #3).
    A segment that needs `need` x more time than its slot splits it evenly: the picture slows by
    sqrt(need) (up to max_slow) and the speech speeds up by the rest (up to max_stretch).
    Times are on the output timeline (`out_start`), which is longer wherever the video slows.
    Each segment aims for its own start, so a late segment can only delay the next one until a
    pause absorbs it: delay never accumulates over the clip."""
    prev_end, shift = 0.0, 0.0  # shift = output time added by slowed video so far
    for i, s in enumerate(segs):
        next_start = segs[i + 1]["start"] if i + 1 < len(segs) else total
        slot = max(next_start - s["start"], 0.01)
        need = max(s["tts_dur"] / slot, 1.0)
        slow = min(need ** 0.5, max_slow)
        stretch = min(need / slow, max_stretch)
        dur = s["tts_dur"] / stretch
        out_start = s["start"] + shift
        placed = max(out_start, prev_end)
        s.update(stretch=round(stretch, 3), slow=round(slow, 3), out_start=round(out_start, 3),
                 placed_start=round(placed, 3), overflow=round(max(0.0, placed + dur - (out_start + slot * slow)), 3))
        prev_end = placed + dur
        shift += slot * (slow - 1)
    return segs


def out_duration(segs: list[dict], total: float) -> float:
    """Length of the output video after slowing."""
    if not segs:
        return total
    last = segs[-1]
    return last["out_start"] + (total - last["start"]) * last.get("slow", 1.0)


def run(video: Path, work: Path, cfg: dict) -> None:
    data = read_json(work / "segments.json")
    total = video_duration(video)  # not the audio length: the source audio can end before the picture
    segs = place(data["segments"], total, cfg["max_stretch"], cfg["max_video_slow"])
    total = out_duration(segs, total)

    track, sr = None, None
    for s in segs:
        wav = work / "tts" / f"{s['id']}.wav"
        if s["stretch"] > 1.0:
            fitted = work / "tts" / f"{s['id']}.fit.wav"
            ffmpeg("-i", str(wav), "-filter:a", f"atempo={s['stretch']}", str(fitted))  # keeps pitch
            wav = fitted
        audio, sr = sf.read(wav, dtype="float32")
        if track is None:
            track = np.zeros(int(total * sr) + 1, dtype="float32")
        a = int(s["placed_start"] * sr)
        if a + len(audio) > len(track):  # last segment runs past the video end; mux cuts it
            track = np.pad(track, (0, a + len(audio) - len(track)))
        track[a:a + len(audio)] += audio

    # loudness match: TTS voices come out at their own level (MMS was ~6 dB louder than the narrator,
    # which buried the music); scale the dub to the source voice level over the speech, within +-12 dB
    src = work / "vocals.wav" if (work / "vocals.wav").exists() else work / "audio.wav"
    x, xsr = sf.read(src, dtype="float32")
    src_db = db(np.concatenate([x[int(s["start"] * xsr):int(s["end"] * xsr)] for s in segs]))
    dub_db = db(np.concatenate([track[int(s["placed_start"] * sr):int((s["placed_start"] + s["tts_dur"] / s["stretch"]) * sr)]
                                for s in segs]))
    gain_db = float(np.clip(src_db - dub_db, -12, 12))
    data["dub_gain_db"] = round(gain_db, 1)
    sf.write(work / "dub.wav", np.clip(track * 10 ** (gain_db / 20), -1, 1), sr)
    write_json(work / "segments.json", data)
