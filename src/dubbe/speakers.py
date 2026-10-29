"""C7: who speaks when - one speaker label per sentence.

A speaker-verification model (WavLM base plus SV, MIT) gives each sentence a voice fingerprint; sentences whose
fingerprints are close (cosine distance, average linkage) are one speaker. Sentences shorter than MIN_S give unsteady
fingerprints, so they join the nearest speaker afterwards, and a "speaker" with less than MIN_TOTAL_S of speech joins
the nearest one too. Speakers are numbered by how much they say (S1 = the main speaker). The threshold is calibrated
in test-results C21. Sentence level only: two people inside one sentence stay one speaker.
A reviewer's corrections (data["speakers_edited"]) are never redone.
"""
from pathlib import Path

import numpy as np
import soundfile as sf

from . import device, free_gpu, read_json, write_json

MODEL = "microsoft/wavlm-base-plus-sv"
MIN_S = 1.0
MIN_TOTAL_S = 3.0


def fingerprints(clips: list[np.ndarray]) -> np.ndarray:
    """One unit-length voice fingerprint per 16 kHz clip."""
    import torch
    from transformers import AutoFeatureExtractor, WavLMForXVector
    dev = device()
    fe, model = AutoFeatureExtractor.from_pretrained(MODEL), WavLMForXVector.from_pretrained(MODEL).to(dev).eval()
    out = []
    with torch.no_grad():
        for c in clips:
            e = model(**fe(c, sampling_rate=16000, return_tensors="pt").to(dev)).embeddings
            out.append(torch.nn.functional.normalize(e, dim=-1)[0].cpu().numpy())
    del model
    free_gpu()
    return np.array(out)


def cluster(emb: np.ndarray, durs: list[float], threshold: float) -> list[int]:
    """Speaker number per sentence (0 = says the most)."""
    from scipy.cluster.hierarchy import fcluster, linkage
    long_ = [i for i, d in enumerate(durs) if d >= MIN_S] or list(range(len(durs)))
    labels = np.zeros(len(durs), int)
    if len(long_) > 1:
        labels[long_] = fcluster(linkage(emb[long_], "average", metric="cosine"), t=threshold, criterion="distance")
    else:
        labels[long_] = 1
    while True:  # tiny "speakers" (and the short sentences, label 0) join the nearest real one
        total = {k: sum(d for d, lab in zip(durs, labels) if lab == k) for k in set(labels) if k}
        small = [k for k, t in total.items() if t < MIN_TOTAL_S]
        if len(total) <= 1 or not small:
            break
        labels[labels == min(small, key=total.get)] = 0
    keep = sorted(set(labels) - {0})
    if not keep:
        return [0] * len(durs)
    centre = {k: emb[labels == k].mean(0) for k in keep}
    for i in np.where(labels == 0)[0]:
        labels[i] = max(keep, key=lambda k: float(emb[i] @ centre[k]))
    order = sorted(keep, key=lambda k: -sum(d for d, lab in zip(durs, labels) if lab == k))
    return [order.index(lab) for lab in labels]


def run(video: Path, work: Path, cfg: dict) -> None:
    data = read_json(work / "segments.json")
    segs = data["segments"]
    if data.get("speakers_edited") or not segs:
        return
    wav = work / "vocals.wav" if (work / "vocals.wav").exists() else work / "audio.wav"
    x, sr = sf.read(wav, dtype="float32")
    x = x.mean(1) if x.ndim > 1 else x
    clips = [x[int(s["start"] * sr):int(s["end"] * sr)] for s in segs]
    clips16 = [np.interp(np.arange(0, len(c), sr / 16000), np.arange(len(c)), c).astype("float32") if len(c) > 1
               else np.zeros(1600, "float32") for c in clips]
    labels = cluster(fingerprints(clips16), [s["end"] - s["start"] for s in segs], cfg["speaker_threshold"])
    for s, lab in zip(segs, labels):
        s["speaker"] = f"S{lab + 1}"
    data["speakers"] = {f"S{k + 1}": {"name": f"Speaker {k + 1}"} for k in sorted(set(labels))}
    print(f"         {len(data['speakers'])} speaker(s)")
    write_json(work / "segments.json", data)
