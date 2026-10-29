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


def fade(audio: np.ndarray, sr: int, s: float = .01) -> np.ndarray:
    """10 ms fade in and out, so a sentence never starts or ends with a click."""
    n = min(int(s * sr), len(audio) // 2)
    if n:
        audio, ramp = audio.copy(), np.linspace(0, 1, n, dtype=audio.dtype)
        audio[:n] *= ramp
        audio[-n:] *= ramp[::-1]
    return audio


def limit(x: np.ndarray, knee: float = .9) -> np.ndarray:
    """Soft limiter: peaks above the knee bend smoothly towards full scale instead of clipping with a crackle."""
    over = np.abs(x) > knee
    x = x.copy()
    x[over] = np.sign(x[over]) * (knee + (1 - knee) * np.tanh((np.abs(x[over]) - knee) / (1 - knee)))
    return x


def relative(clips: list[np.ndarray], sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Loudness (dB) and pitch (semitones) of each sentence relative to the speaker's median over all sentences:
    how the original delivered it - louder and higher when excited or shouting, softer and lower when sad or quiet.
    Pitch is 0 where a sentence is too short to measure."""
    from .voice import median_f0
    lv = np.array([db(c) for c in clips])
    f0 = np.array([median_f0(c, sr) if len(c) > .5 * sr else np.nan for c in clips])
    st = 12 * np.log2(f0 / np.nanmedian(f0)) if np.isfinite(f0).any() else np.zeros(len(clips))
    return lv - np.median(lv), np.nan_to_num(st)


def run(video: Path, work: Path, cfg: dict) -> None:
    data = read_json(work / "segments.json")
    total = video_duration(video)  # not the audio length: the source audio can end before the picture
    segs = place(data["segments"], total, cfg["max_stretch"], cfg["max_video_slow"])
    total = out_duration(segs, total)
    src = work / "vocals.wav" if (work / "vocals.wav").exists() else work / "audio.wav"
    x, xsr = sf.read(src, dtype="float32")
    x = x.mean(1) if x.ndim > 1 else x
    orig = [x[int(s["start"] * xsr):int(s["end"] * xsr)] for s in segs]
    follow = cfg.get("follow_delivery") and len(segs) > 2
    o_db, o_st = relative(orig, xsr) if follow else (np.zeros(len(segs)), np.zeros(len(segs)))

    clips, sr = [], None
    for i, s in enumerate(segs):
        # emotion through delivery: part of the original sentence's pitch movement (rubberband keeps the formants)
        st = float(np.clip(cfg["delivery_pitch"] * o_st[i], -cfg["delivery_max_st"], cfg["delivery_max_st"]))
        st = st if abs(st) >= .3 else 0.0
        filters = ([f"rubberband=pitch={2 ** (st / 12):.4f}:formant=preserved"] if st else []) + \
                  ([f"atempo={s['stretch']}"] if s["stretch"] > 1.0 else [])  # atempo keeps pitch
        wav = work / "tts" / f"{s['id']}.wav"
        if filters:
            fitted = work / "tts" / f"{s['id']}.fit.wav"
            ffmpeg("-i", str(wav), "-filter:a", ",".join(filters), str(fitted))
            wav = fitted
        audio, sr = sf.read(wav, dtype="float32")
        clips.append(fade(audio, sr))
        s["delivery_st"] = round(st, 2)
    if follow:  # ... and its loudness: each sentence as much louder or softer than the dub's median as in the original
        d_db = np.array([db(c) for c in clips])
        for i, (c, rel) in enumerate(zip(clips, d_db - np.median(d_db))):
            g = float(np.clip(np.clip(o_db[i], -cfg["delivery_max_db"], cfg["delivery_max_db"]) - rel, -12, 12))
            clips[i], segs[i]["delivery_db"] = c * 10 ** (g / 20), round(g, 1)

    track = np.zeros(int(total * sr) + 1, dtype="float32")
    for s, audio in zip(segs, clips):
        a = int(s["placed_start"] * sr)
        if a + len(audio) > len(track):  # last segment runs past the video end; mux cuts it
            track = np.pad(track, (0, a + len(audio) - len(track)))
        track[a:a + len(audio)] += audio

    # loudness match: TTS voices come out at their own level (MMS was ~6 dB louder than the narrator,
    # which buried the music); scale the dub to the source voice level over the speech, within +-12 dB
    src_db = db(np.concatenate(orig))
    dub_db = db(np.concatenate([track[int(s["placed_start"] * sr):int((s["placed_start"] + s["tts_dur"] / s["stretch"]) * sr)]
                                for s in segs]))
    gain_db = float(np.clip(src_db - dub_db, -12, 12))
    data["dub_gain_db"] = round(gain_db, 1)
    track *= 10 ** (gain_db / 20)
    sf.write(work / "dub.wav", limit(track), sr)
    write_json(work / "segments.json", data)
