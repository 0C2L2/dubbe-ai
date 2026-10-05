from pathlib import Path

import soundfile as sf

from . import free_gpu, read_json, video_duration, write_json
from .tts import ENGINES, trim, tts_cfg


def pick(alts: list[dict], current: str, min_ratio: float) -> str | None:
    """Shortest alternative translation that is shorter than `current` and whose
    confidence is at least min_ratio of the best one; None if there is none."""
    ok = [a for a in alts if a["conf"] >= min_ratio * alts[0]["conf"] and len(a["text"]) < len(current)]
    return min(ok, key=lambda a: len(a["text"]))["text"] if ok else None


def run(video: Path, work: Path, cfg: dict) -> None:
    """Target T-08: when synthesized speech cannot fit its slot even at max_stretch,
    swap in a shorter alternative translation and re-synthesize it."""
    data = read_json(work / "segments.json")
    segs, total = data["segments"], video_duration(video)
    todo = []
    for i, s in enumerate(segs):
        slot = (segs[i + 1]["start"] if i + 1 < len(segs) else total) - s["start"]
        s["shortened"] = False
        if s["edited"] or not s.get("alts") or s["tts_dur"] <= slot * cfg["max_stretch"] * cfg["max_video_slow"]:
            continue
        text = pick(s["alts"], s["tgt_text"], cfg["shorten_min_conf_ratio"])
        if text:
            todo.append((s, text))

    if todo:
        tts = tts_cfg(data, cfg)
        for (s, text), (audio, sr) in zip(todo, ENGINES[tts["engine"]]([t for _, t in todo], tts)):
            audio = trim(audio)
            if len(audio) / sr < s["tts_dur"]:  # keep only if the speech really got shorter
                sf.write(work / "tts" / f"{s['id']}.wav", audio, sr)
                s.update(tgt_text=text, tts_dur=round(len(audio) / sr, 3), shortened=True,
                         mt_conf=next(a["conf"] for a in s["alts"] if a["text"] == text))
        free_gpu()
    print(f"         shortened {sum(s['shortened'] for s in segs)} of {len(todo)} overflowing segments")
    write_json(work / "segments.json", data)
