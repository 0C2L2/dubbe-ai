"""C21/C28/C31: who speaks when, from the audio itself, before sentences are formed.

NVIDIA Nemotron 3 Diarization (OpenMDW 1.1) finds the speaker turns: where each piece of speech starts and ends.
Its own labels merge similar voices (12 known voices: it found 7), so every turn is then given a TitaNet-large voice
fingerprint (NVIDIA, CC-BY-4.0) and the turns are grouped by voice from scratch (same average-linkage grouping as
`speakers.cluster`) - 12 of 12 voices, 3 of 3 similar women, 4 of 4 voices right (test results C31). Both models run
in .venv-nemo, in one load (nemotron_worker.py). `segment` then splits sentences where the speaker changes and
`speakers` names each sentence by the turn it overlaps most. speaker_engine: wavlm, or no .venv-nemo, writes no
diarization.json and `speakers` falls back to per-sentence WavLM fingerprints.
"""
import json
import os
import subprocess
from pathlib import Path

import numpy as np

from . import write_json

MODEL = "nvidia/Nemotron-3-Diarization + nvidia/speakerverification_en_titanet_large"
NEMO_PY = Path(__file__).parents[2] / ".venv-nemo" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def who(turns: list[dict], start: float, end: float) -> str | None:
    """The speaker whose turns overlap [start, end] most; with no overlap, the speaker of the nearest turn."""
    if not turns:
        return None
    ov = {}
    for t in turns:
        o = min(end, t["end"]) - max(start, t["start"])
        if o > 0:
            ov[t["speaker"]] = ov.get(t["speaker"], 0.0) + o
    if ov:
        return max(ov, key=ov.get)
    mid = (start + end) / 2
    return min(turns, key=lambda t: max(t["start"] - mid, mid - t["end"]))["speaker"]


def regroup(turns: list[dict], emb: np.ndarray, threshold: float) -> list[dict]:
    """The turns' speakers decided by their voice fingerprints alone (Nemotron's own labels are dropped)."""
    from .speakers import cluster
    if len(turns) < 2:
        return [{**t, "speaker": "SPEAKER_00"} for t in turns]
    labels = cluster(emb, [t["end"] - t["start"] for t in turns], threshold)
    return [{**t, "speaker": f"SPEAKER_{lab:02d}"} for t, lab in zip(turns, labels)]


def _worker(job: dict) -> dict:
    p = subprocess.run([str(NEMO_PY), "-I", str(Path(__file__).with_name("nemotron_worker.py"))], capture_output=True,
                       text=True, encoding="utf-8", input=json.dumps(job))
    if p.returncode:
        raise RuntimeError(f"nemotron_worker failed: {p.stderr[-2000:]}")
    return json.loads(p.stdout.strip().splitlines()[-1])


def embed_spans(wav: Path, spans: list[list[float]]) -> np.ndarray:
    """TitaNet voice fingerprints of time spans (unit vectors) - used by `speakers` for parts of sentences."""
    return np.array(_worker({"wav": str(Path(wav).resolve()), "spans": spans})["emb"]) if spans else np.zeros((0, 192))


def run(video: Path, work: Path, cfg: dict) -> None:
    out = work / "diarization.json"
    out.unlink(missing_ok=True)  # never leave turns from an earlier run behind
    if cfg.get("speaker_engine", "nemotron") != "nemotron":
        return
    if not NEMO_PY.exists():
        print("         no .venv-nemo: speakers are found per sentence instead (voice fingerprints)")
        return
    wav = work / "vocals.wav" if (work / "vocals.wav").exists() else work / "audio.wav"
    res = _worker({"wav": str(wav.resolve())})
    emb = np.array(res["emb"])
    turns = regroup(res["turns"], emb, cfg["speaker_group_threshold"])
    for t, e in zip(turns, emb):  # kept for `speakers` (C33): it compares voices without loading the model again
        t["emb"] = [round(float(v), 4) for v in e]
    write_json(out, {"model": MODEL, "turns": turns})
    print(f"         {len({t['speaker'] for t in turns})} speaker(s), {len(turns)} turns")
