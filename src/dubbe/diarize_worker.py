"""Runs pyannote 4 (speaker-diarization-community-1, CC-BY-4.0) in .venv-diarize: pyannote.audio 4 needs numpy and
packages that the main environment does not have. stdin: {"wav": path, "model": id}; stdout: [{start, end, speaker}].
HF_TOKEN comes from the environment. pyannote's usage telemetry is switched off: nothing leaves this machine."""
import json
import os
import sys

os.environ["PYANNOTE_METRICS_ENABLED"] = "0"

import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from pyannote.audio import Pipeline  # noqa: E402

job = json.load(sys.stdin)
pipe = Pipeline.from_pretrained(job["model"], token=os.environ.get("HF_TOKEN"))
pipe.to(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
x, sr = sf.read(job["wav"], dtype="float32", always_2d=True)
out = pipe({"waveform": torch.from_numpy(x.mean(1))[None], "sample_rate": sr})
ann = getattr(out, "speaker_diarization", out)  # pyannote 4 returns an object holding the annotation
print(json.dumps([{"start": round(t.start, 3), "end": round(t.end, 3), "speaker": s}
                  for t, _, s in ann.itertracks(yield_label=True)]))
