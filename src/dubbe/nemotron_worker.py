"""Runs in .venv-nemo (NeMo from GitHub main, for Nemotron's rotary attention). Two jobs on stdin:
- {"wav": path}: NVIDIA Nemotron 3 Diarization (OpenMDW 1.1) finds the speaker turns, then TitaNet-large (CC-BY-4.0)
  gives each turn a voice fingerprint - one process, so both models load once.
  stdout (last line): {"turns": [{start, end, speaker}], "emb": [[unit vector] per turn]}
- {"wav": path, "spans": [[start, end], ...]}: TitaNet fingerprints of those time spans only (`speakers` checks
  who said part of a sentence). stdout (last line): {"emb": [[unit vector] per span]}
Test results C28, C31, C33."""
import json
import re
import sys

import numpy as np
import soundfile as sf
import torch

torch._dynamo.config.disable = True  # torch.compile needs Triton, which has no Windows build: run the models eagerly
from nemo.collections.asr.models import EncDecSpeakerLabelModel, SortformerEncLabelModel  # noqa: E402

job = json.load(sys.stdin)
dev = "cuda" if torch.cuda.is_available() else "cpu"


def fingerprints(spans):
    model = EncDecSpeakerLabelModel.from_pretrained("nvidia/speakerverification_en_titanet_large", map_location=dev).eval()
    x, sr = sf.read(job["wav"], dtype="float32")
    x = x.mean(1) if x.ndim > 1 else x
    out = []
    with torch.no_grad():
        for a, b in spans:
            sig = torch.tensor(np.pad(x[int(a * sr):int(b * sr)], (0, sr // 2)))[None].to(dev)  # >= 0.5 s
            _, e = model.forward(input_signal=sig, input_signal_length=torch.tensor([sig.shape[1]], device=dev))
            v = e[0].cpu().numpy()
            out.append((v / np.linalg.norm(v)).tolist())
    return out


if "spans" in job:
    print(json.dumps({"emb": fingerprints(job["spans"])}))
    sys.exit()

diar = SortformerEncLabelModel.from_pretrained("nvidia/Nemotron-3-Diarization", map_location=dev).eval()
with torch.no_grad():
    res = diar.diarize(audio=[job["wav"]], batch_size=1)
segs = res[0] if res and isinstance(res[0], (list, tuple)) else res
turns = []
for s in segs:  # "begin end speaker_N"
    b, e, spk = s.replace(",", " ").split()[:3]
    turns.append({"start": round(float(b), 3), "end": round(float(e), 3),
                  "speaker": f"SPEAKER_{int(re.sub(r'\D', '', spk) or 0):02d}"})
turns.sort(key=lambda t: t["start"])
del diar
torch.cuda.empty_cache()
print(json.dumps({"turns": turns, "emb": fingerprints([[t["start"], t["end"]] for t in turns])}))
