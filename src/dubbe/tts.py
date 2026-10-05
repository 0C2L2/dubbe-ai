from pathlib import Path

import numpy as np
import soundfile as sf

from . import device, free_gpu, read_json, write_json


def _kokoro(texts: list[str], tts: dict):
    from kokoro import KPipeline

    pipe = KPipeline(lang_code=tts["voice"][0])  # Kokoro voice ids start with their accent code: a=US, b=UK, ...
    for text in texts:
        yield np.concatenate([np.asarray(a) for _, _, a in pipe(text, voice=tts["voice"], speed=1.0)]), 24000


def _mms(texts: list[str], tts: dict):
    # Meta MMS-TTS (VITS), one model per language, CC BY-NC 4.0; non-Latin scripts need `uroman`
    import torch
    from transformers import AutoTokenizer, VitsModel

    dev = device()
    tok = AutoTokenizer.from_pretrained(tts["voice"])
    model = VitsModel.from_pretrained(tts["voice"]).to(dev)
    torch.manual_seed(0)  # VITS samples noise: fixed seed keeps reruns identical
    for text in texts:
        ids = tok(text, return_tensors="pt").to(dev)
        if ids["input_ids"].shape[1] == 0:  # nothing pronounceable
            yield np.zeros(1, dtype="float32"), model.config.sampling_rate
            continue
        with torch.no_grad():
            yield model(**ids).waveform[0].cpu().numpy(), model.config.sampling_rate


# one adapter per engine, not per language
ENGINES = {"kokoro": _kokoro, "mms": _mms}


def tts_cfg(data: dict, cfg: dict) -> dict:
    """Target-language TTS settings with the voice chosen for the speaker (voice stage, C10)."""
    chosen = data.get("speakers", {}).get("S1", {}).get("voice")
    return {**cfg["tgt"]["tts"], **({"voice": chosen} if chosen else {})}


def trim(audio: np.ndarray, threshold: float = 0.01) -> np.ndarray:
    """Cut leading/trailing near-silence so measured durations are honest."""
    loud = np.flatnonzero(np.abs(audio) > threshold)
    return audio[loud[0]:loud[-1] + 1] if loud.size else audio[:0]


def run(video: Path, work: Path, cfg: dict) -> None:
    data = read_json(work / "segments.json")
    tts = tts_cfg(data, cfg)
    if tts["engine"] not in ENGINES:
        raise SystemExit(f"TTS engine '{tts['engine']}' is not implemented yet (have: {', '.join(ENGINES)})")

    out_dir = work / "tts"
    out_dir.mkdir(exist_ok=True)
    segs = data["segments"]
    for s, (audio, sr) in zip(segs, ENGINES[tts["engine"]]([s["tgt_text"] for s in segs], tts)):
        audio = trim(audio)
        sf.write(out_dir / f"{s['id']}.wav", audio, sr)
        s["tts_dur"] = round(len(audio) / sr, 3)
    free_gpu()
    write_json(work / "segments.json", data)
