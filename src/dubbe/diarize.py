"""C21: who speaks when, from the audio itself (speaker diarization), before sentences are formed.

pyannote/speaker-diarization-3.1 (MIT) finds speaker turns and the number of speakers on its own; `segment` then splits
sentences where the speaker changes and `speakers` names each sentence by the turn it overlaps most. The model is gated:
accept its terms (and pyannote/segmentation-3.0's) on Hugging Face and set HF_TOKEN. Without a token, or with
speaker_engine: wavlm, no diarization.json is written and `speakers` falls back to per-sentence voice fingerprints.
"""
import os
from pathlib import Path

import soundfile as sf

from . import device, free_gpu, write_json

MODEL = "pyannote/speaker-diarization-3.1"
COMMUNITY = "pyannote/speaker-diarization-community-1"  # pyannote 4, run by diarize_worker.py in .venv-diarize
DIARIZE_PY = Path(__file__).parents[2] / ".venv-diarize" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def community_turns(wav: Path) -> list[dict]:
    import json
    import subprocess
    p = subprocess.run([str(DIARIZE_PY), "-I", str(Path(__file__).with_name("diarize_worker.py"))],
                       input=json.dumps({"wav": str(wav.resolve()), "model": COMMUNITY}), capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"diarize_worker failed: {p.stderr[-2000:]}")
    return json.loads(p.stdout.strip().splitlines()[-1])


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


def pipeline():
    """The pyannote pipeline built from local files. pyannote 3.4 downloads with `use_auth_token`, which current
    huggingface_hub no longer accepts, so the pipeline and its two sub-models are fetched here and passed as paths."""
    import yaml
    from huggingface_hub import snapshot_download
    from pyannote.audio.pipelines import SpeakerDiarization
    token = os.environ.get("HF_TOKEN") or None
    conf = yaml.safe_load((Path(snapshot_download(MODEL, token=token)) / "config.yaml").read_text())
    params = dict(conf["pipeline"]["params"])
    for key in ("segmentation", "embedding"):  # Hugging Face ids -> local checkpoint files
        params[key] = str(Path(snapshot_download(params[key], token=token)) / "pytorch_model.bin")
    import torch
    from pyannote.audio.core.task import Problem, Resolution, Specifications
    # torch >= 2.6 loads checkpoints weights-only; allow just the few plain classes pyannote 3 stores in them
    with torch.serialization.safe_globals([torch.torch_version.TorchVersion, Specifications, Problem, Resolution]):
        pipe = SpeakerDiarization(**params)
    pipe.instantiate(conf["params"])
    return pipe


def turns(wav: Path) -> list[dict]:
    """Speaker turns [{start, end, speaker}] in time order; overlapping speech gives overlapping turns."""
    import torch
    pipe = pipeline()
    pipe.to(torch.device(device()))
    x, sr = sf.read(wav, dtype="float32", always_2d=True)
    result = pipe({"waveform": torch.from_numpy(x.mean(1))[None], "sample_rate": sr})  # pyannote resamples to 16 kHz
    out = [{"start": round(t.start, 3), "end": round(t.end, 3), "speaker": spk}
           for t, _, spk in result.itertracks(yield_label=True)]
    del pipe
    free_gpu()
    return out


def run(video: Path, work: Path, cfg: dict) -> None:
    out = work / "diarization.json"
    out.unlink(missing_ok=True)  # never leave turns from an earlier run behind
    engine = cfg.get("speaker_engine", "wavlm")
    if engine not in ("pyannote", "community"):
        return
    if engine == "community" and not DIARIZE_PY.exists():
        print("         no .venv-diarize: speakers are found per sentence instead (voice fingerprints)")
        return
    if not os.environ.get("HF_TOKEN"):
        from huggingface_hub import get_token
        if not get_token():
            print("         no HF_TOKEN: speakers are found per sentence instead (voice fingerprints)")
            return
    wav = work / "vocals.wav" if (work / "vocals.wav").exists() else work / "audio.wav"
    t = community_turns(wav) if engine == "community" else turns(wav)
    write_json(out, {"model": COMMUNITY if engine == "community" else MODEL, "turns": t})
    print(f"         {len({x['speaker'] for x in t})} speaker(s), {len(t)} turns")
