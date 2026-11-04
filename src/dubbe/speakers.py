"""C7: who speaks when - one speaker label per sentence.

With speaker turns from `diarize` (Nemotron + TitaNet, C31) a sentence gets the speaker it overlaps most; otherwise a
speaker-verification model (WavLM base plus SV, MIT) gives each sentence a voice fingerprint; sentences whose
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
from .diarize import who

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


def _span(ws: list[dict], idx: list[int]) -> list[float]:
    return [ws[idx[0]]["start"], ws[idx[-1]]["end"]]


def word_runs(ws: list[dict], turns: list[dict]) -> list[list]:
    """Each word's speaker from the turn that covers it most (by time), in runs: [[speaker, [word indices]], ...]."""
    runs = []
    for i, w in enumerate(ws):
        lab = who(turns, w["start"], w["end"])
        if runs and runs[-1][0] == lab:
            runs[-1][1].append(i)
        else:
            runs.append([lab, [i]])
    return runs


def resolve(ws: list[dict], runs: list[list], cfg: dict, voice) -> tuple[list, bool]:
    """Speaker per word of one sentence (C33). Its longest run is kept. Another run is kept - the sentence will be
    split there - when it is a real block at a pause (>= split_min_words words, >= split_min_s, a gap >= split_gap
    next to it), or when it lasts >= handover_min_s and voice(speaker, neighbour, span) says its voice is its own
    speaker's (a hand-over in mid-sentence, often with no pause). Otherwise its words are bleed from the audio split
    and take the nearest kept run's speaker. The flag marks the sentence for review when a part of >= 0.5 s was
    given to someone else without proof."""
    dur = lambda k: _span(ws, runs[k][1])[1] - _span(ws, runs[k][1])[0]  # noqa: E731
    main = max(range(len(runs)), key=dur)
    keep, flag = [k == main for k in range(len(runs))], False
    for k, (lab, idx) in enumerate(runs):
        if k == main:
            continue
        if dur(k) < cfg["handover_min_s"]:
            flag |= dur(k) >= 0.5
            continue
        gaps = [ws[idx[0]]["start"] - ws[runs[k - 1][1][-1]]["end"] if k else 0.0,
                ws[runs[k + 1][1][0]]["start"] - ws[idx[-1]]["end"] if k + 1 < len(runs) else 0.0]
        if len(idx) >= cfg["split_min_words"] and dur(k) >= cfg["split_min_s"] and max(gaps) >= cfg["split_gap"]:
            keep[k] = True
            continue
        nb = max((j for j in (k - 1, k + 1) if 0 <= j < len(runs)), key=dur)
        keep[k] = bool(voice(lab, runs[nb][0], _span(ws, idx)))
        flag |= not keep[k]
    kept = [k for k in range(len(runs)) if keep[k]]
    labels = [None] * len(ws)
    for k, (lab, idx) in enumerate(runs):
        to = lab if keep[k] else runs[min(kept, key=lambda j: (abs(j - k), -dur(j)))][0]
        for i in idx:
            labels[i] = to
    return labels, flag


def assign(segs: list[dict], words: list[dict], turns: list[dict], cfg: dict, voice, join: str = " ") -> tuple[list, list]:
    """Every sentence gets its speakers from its words (`resolve`); a sentence that two people share is split there.
    Returns the (possibly more) sentences and a diarization speaker label for each."""
    out, labels = [], []
    for s in segs:
        ws = [w for w in words if s["start"] - 1e-3 <= w["start"] and w["end"] <= s["end"] + 1e-3]
        if not ws:
            out.append({k: v for k, v in s.items() if k != "speaker_flag"})
            labels.append(who(turns, s["start"], s["end"]))
            continue
        runs = word_runs(ws, turns)
        wl, flag = resolve(ws, runs, cfg, voice) if len(runs) > 1 else ([runs[0][0]] * len(ws), False)
        parts = []
        for w, lab in zip(ws, wl):
            if parts and parts[-1][0] == lab:
                parts[-1][1].append(w)
            else:
                parts.append([lab, [w]])
        for lab, pw in parts:
            n = {k: v for k, v in s.items() if k != "speaker_flag"}
            if len(parts) > 1:
                sc = [w["score"] for w in pw if "score" in w]
                n.update(start=pw[0]["start"], end=pw[-1]["end"], src_text=join.join(w["w"] for w in pw), tgt_text=None,
                         edited=False, asr_conf=round(sum(sc) / len(sc), 3) if sc else None)
            if flag:
                n["speaker_flag"] = True  # maybe two people in this sentence: check in review
            out.append(n)
            labels.append(lab)
    return out, labels


def profiles(turns: list[dict]) -> dict:
    """Voice print per diarization speaker: the duration-weighted mean of its turns' TitaNet fingerprints."""
    acc = {}
    for t in turns:
        if t.get("emb"):
            acc[t["speaker"]] = acc.get(t["speaker"], 0) + (t["end"] - t["start"]) * np.array(t["emb"])
    return {k: v / (np.linalg.norm(v) or 1) for k, v in acc.items()}


def name_speakers(segs: list[dict], raw: list, prof: dict, cfg: dict) -> tuple[list[int], dict]:
    """Speaker number per sentence (0 = says the most) and "maybe the same person" pairs. A speaker with less than
    MIN_TOTAL_S of sentences is a stray label: those sentences take the previous sentence's speaker. Two speakers
    whose voice prints are closer than merge_auto are one person (merged); closer than merge_ask: asked in review."""
    raw = list(raw)
    durs = [s["end"] - s["start"] for s in segs]
    total = lambda: {k: sum(d for d, r in zip(durs, raw) if r == k) for k in set(raw)}  # noqa: E731
    tot = total()
    big = {k for k, t in tot.items() if t >= MIN_TOTAL_S} or {max(tot, key=tot.get)}
    for i, r in enumerate(raw):
        if r not in big:
            raw[i] = next((raw[j] for j in range(i - 1, -1, -1) if raw[j] in big),
                          next((raw[j] for j in range(i + 1, len(raw)) if raw[j] in big), max(big, key=tot.get)))
    pairs = sorted((1 - float(prof[a] @ prof[b]), a, b) for a in big for b in big if a < b and a in prof and b in prof)
    ask = []
    for d, a, b in pairs:
        if a not in set(raw) or b not in set(raw):
            continue  # already merged away
        if d < cfg["merge_auto"]:
            tot = total()
            keep_, gone = (a, b) if tot[a] >= tot[b] else (b, a)
            raw = [keep_ if r == gone else r for r in raw]
        elif d < cfg["merge_ask"]:
            ask.append((a, b))
    order = sorted(set(raw), key=lambda k: -total()[k])
    maybe = {}
    for a, b in ask:
        if a in order and b in order and a != b:
            maybe.setdefault(order.index(a), set()).add(order.index(b))
            maybe.setdefault(order.index(b), set()).add(order.index(a))
    return [order.index(r) for r in raw], maybe


def run(video: Path, work: Path, cfg: dict) -> None:
    data = read_json(work / "segments.json")
    segs = data["segments"]
    if data.get("speakers_edited") or not segs:
        return
    diar = work / "diarization.json"
    turns = read_json(diar)["turns"] if diar.exists() else None
    maybe = {}
    if turns:
        from .diarize import embed_spans
        prof = profiles(turns)
        words = read_json(work / "words.json")["words"]
        wav = work / "vocals.wav" if (work / "vocals.wav").exists() else work / "audio.wav"
        asked = []  # pass 1: which parts of sentences need a voice check (all fingerprinted in one model load)
        assign(segs, words, turns, cfg, lambda a, b, span: asked.append(span), cfg["src"].get("join", " "))
        emb = dict(zip(map(tuple, asked), embed_spans(wav, asked))) if asked and prof else {}

        def voice(lab, other, span):
            e = emb.get(tuple(span))
            if e is None or lab not in prof or other not in prof:
                return None
            return 1 - float(e @ prof[lab]) + cfg["handover_margin"] < 1 - float(e @ prof[other])
        segs, raw = assign(segs, words, turns, cfg, voice, cfg["src"].get("join", " "))
        for n, s in enumerate(segs, 1):
            s["id"] = n
        data["segments"] = segs
        labels, maybe = name_speakers(segs, raw, prof, cfg)
    else:
        wav = work / "vocals.wav" if (work / "vocals.wav").exists() else work / "audio.wav"
        x, sr = sf.read(wav, dtype="float32")
        x = x.mean(1) if x.ndim > 1 else x
        clips = [x[int(s["start"] * sr):int(s["end"] * sr)] for s in segs]
        clips16 = [np.interp(np.arange(0, len(c), sr / 16000), np.arange(len(c)), c).astype("float32") if len(c) > 1
                   else np.zeros(1600, "float32") for c in clips]
        labels = cluster(fingerprints(clips16), [s["end"] - s["start"] for s in segs], cfg["speaker_threshold"])
    for s, lab in zip(segs, labels):
        s["speaker"] = f"S{lab + 1}"
    data["speakers"] = {f"S{k + 1}": {"name": f"Speaker {k + 1}"} | ({"maybe_same": sorted(f"S{j + 1}" for j in maybe[k])}
                                                                     if k in maybe else {}) for k in sorted(set(labels))}
    print(f"         {len(data['speakers'])} speaker(s), {sum(1 for s in segs if s.get('speaker_flag'))} sentence(s) to check")
    write_json(work / "segments.json", data)
