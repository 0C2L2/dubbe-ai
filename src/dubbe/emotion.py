"""Delivery tags heard in the original: every source sentence is listened to by two classifiers and its text is read,
and what they find becomes the sentence's tags, so the translated sentence is spoken the same way (tags.py).

- emotion: superb/hubert-large-superb-er (IEMOCAP: neutral / happy / angry / sad) -> [excited] [angry] [sad], only
  when the model is at least emotion_min sure. CREMA-D (real actors, English, 160 sentences, 77 actors): 68 % right
  over the 4 classes (wav2vec2-base: 44 %); at 0.9, 82 % of its emotion tags were right and it found 34 % of the
  emotional sentences - a wrong emotion is worse than none. Not measured on Korean: no labelled Korean set at hand.
- sounds: the AudioSet classifier (AST, multi-label) -> [laugh] [sigh] [gasp] [cough] [whisper]
- [question]: the original sentence ends with "?"
Tags a reviewer changed (tags_edited) are never touched; auto_tags keeps what was heard, for the editor.
Test results C22."""
from pathlib import Path

import numpy as np
import soundfile as sf

from . import device, free_gpu, read_json, write_json
from .tags import ALL

SER = "superb/hubert-large-superb-er"
AST = "MIT/ast-finetuned-audioset-10-10-0.4593"
EMOTION = {"ang": "angry", "hap": "excited", "sad": "sad"}
SOUNDS = {"laugh": ("Laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"), "sigh": ("Sigh",),
          "gasp": ("Gasp",), "cough": ("Cough",), "whisper": ("Whispering",)}
MIN_EMOTION_S = 0.8  # "Yes." says too little about an emotion


def scores(clips: list[np.ndarray]) -> list[dict]:
    """Per 16 kHz clip: the emotion model's best label and score, and the probability of each sound."""
    import torch
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification, pipeline

    dev = device()
    out = [{"emotion": ("neu", 0.0), "sounds": {}} for _ in clips]
    ser = pipeline("audio-classification", model=SER, device=0 if dev == "cuda" else -1)
    for o, c in zip(out, clips):
        if len(c) >= MIN_EMOTION_S * 16000:
            best = max(ser({"raw": c, "sampling_rate": 16000}, top_k=4), key=lambda r: r["score"])
            o["emotion"] = (best["label"], best["score"])
    del ser
    fe, ast = AutoFeatureExtractor.from_pretrained(AST), AutoModelForAudioClassification.from_pretrained(AST).to(dev)
    ids = {t: [ast.config.label2id[n] for n in names] for t, names in SOUNDS.items()}
    with torch.no_grad():
        for o, c in zip(out, clips):
            p = torch.sigmoid(ast(**fe(c, sampling_rate=16000, return_tensors="pt").to(dev)).logits[0]).cpu().numpy()
            o["sounds"] = {t: float(p[i].max()) for t, i in ids.items()}
    del ast
    free_gpu()
    return out


def tags_for(sc: dict, text: str, cfg: dict) -> list[str]:
    label, score = sc["emotion"]
    found = [EMOTION[label]] if label in EMOTION and score >= cfg["emotion_min"] else []
    found += [t for t, p in sc["sounds"].items() if p >= cfg["sound_min"]]
    found += ["question"] if text.rstrip().endswith("?") else []
    return [t for t in ALL if t in found]


def run(video: Path, work: Path, cfg: dict) -> None:
    data = read_json(work / "segments.json")
    todo = [s for s in data["segments"] if not s.get("tags_edited")]  # the reviewer's tags always win
    if not cfg.get("auto_tags") or not todo:
        return
    wav = work / "vocals.wav" if (work / "vocals.wav").exists() else work / "audio.wav"  # music out, when separated
    x, sr = sf.read(wav, dtype="float32")
    x = x.mean(1) if x.ndim > 1 else x
    x = np.interp(np.arange(0, len(x), sr / 16000), np.arange(len(x)), x).astype("float32") if sr != 16000 else x
    clips = [x[int(s["start"] * 16000):int(s["end"] * 16000)] for s in todo]
    for s, sc in zip(todo, scores(clips)):
        s["auto_tags"] = s["tags"] = tags_for(sc, s["src_text"], cfg)
    counts = {t: sum(t in s["tags"] for s in todo) for t in ALL}
    print(f"         {sum(bool(s['tags']) for s in todo)} of {len(todo)} sentences tagged "
          f"({', '.join(f'{t} {n}' for t, n in counts.items() if n) or 'none'})")
    write_json(work / "segments.json", data)
