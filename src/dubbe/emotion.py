"""Delivery tags heard in the original: every source sentence is listened to by two classifiers and its text is read,
and what they find becomes the sentence's tags, so the translated sentence is spoken the same way (tags.py).

- emotion: emotion2vec+ large (FunASR model license: credit the source, keep the model name) -> [excited] [angry]
  [sad] [scared] [surprised] [disgusted], only when the model is at least emotion_min sure - a wrong emotion is worse
  than none. At 0.9 (test-results C39), vs superb/hubert-large-superb-er before: CREMA-D (English actors, 6 emotions,
  180 clips) 93 % of its tags right, 79 % of the emotional clips found (hubert, 4 emotions: 83 % / 33 %); Hi,KIA
  (Korean actors, 488 clips of 0.6 s) 71 % right, 19 % found (hubert 3 tags, 0 found). Calm read speech (FLEURS)
  0 tags, but it is sure of some wrong ones in real videos (narration heard angry): the reviewer removes them.
- sounds: the AudioSet classifier (AST, multi-label) -> [laugh] [sigh] [gasp] [cough] [whisper]
- [question]: the original sentence ends with "?"
Tags a reviewer changed (tags_edited) are never touched; auto_tags keeps what was heard, for the editor.
Test results C22."""
from pathlib import Path

import numpy as np
import soundfile as sf

from . import device, free_gpu, read_json, write_json
from .tags import ALL

SER = "emotion2vec/emotion2vec_plus_large"
AST = "MIT/ast-finetuned-audioset-10-10-0.4593"
EMOTION = {"angry": "angry", "happy": "excited", "sad": "sad", "fearful": "scared", "surprised": "surprised",
           "disgusted": "disgusted"}
SOUNDS = {"laugh": ("Laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"), "sigh": ("Sigh",),
          "gasp": ("Gasp",), "cough": ("Cough",), "whisper": ("Whispering",)}
MIN_EMOTION_S = 0.8  # "Yes." says too little about an emotion


def scores(clips: list[np.ndarray]) -> list[dict]:
    """Per 16 kHz clip: the emotion model's best label and score, and the probability of each sound."""
    import logging

    import torch
    from funasr import AutoModel
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

    logging.getLogger().setLevel(logging.WARNING)  # importing funasr sets INFO: hundreds of lines per load
    dev = device()
    out = [{"emotion": ("neutral", 0.0), "sounds": {}} for _ in clips]
    ser = AutoModel(model=SER, hub="hf", device="cuda:0" if dev == "cuda" else "cpu", disable_update=True,
                    disable_pbar=True)
    for o, c in zip(out, clips):
        if len(c) >= MIN_EMOTION_S * 16000:
            r = ser.generate(c, granularity="utterance", extract_embedding=False)[0]
            k = int(np.argmax(r["scores"]))
            o["emotion"] = (r["labels"][k].split("/")[-1], float(r["scores"][k]))  # "生气/angry" -> "angry"
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
