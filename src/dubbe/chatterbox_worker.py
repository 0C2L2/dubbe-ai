"""Chatterbox worker: Turbo for English, Multilingual for other languages ("lang", e.g. Korean). Runs inside
.venv-chatterbox, NOT the main environment: chatterbox-tts pins torch 2.6 / numpy < 2 / transformers 5.2, which
would break the rest of DUBBE. Does not import dubbe.

stdin:  {"texts": ["[laugh] Hello there.", ...], "out_dir": "...", "lang": "ko", "prompt": null, "prompts": null}   (lang: default English)
stdout: {"sr": 24000}  and out_dir/<i>.wav per text

The built-in voice, unless "prompt" names a reference recording: only a consented clone of the user's own voice, checked
and decrypted by the website for this job (web/clones.py; approved by the instructor, Q-010).
"""
import json
import sys
from pathlib import Path

import soundfile as sf
import torch

job = json.load(sys.stdin)
dev = "cuda" if torch.cuda.is_available() else "cpu"
lang = job.get("lang", "en")
if lang == "en":
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    model, kw = ChatterboxTurboTTS.from_pretrained(device=dev), {}
else:
    import chatterbox.mtl_tts as mtl
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    # Turbo keeps only the speech tokens its voice decoder knows (< 6561); Multilingual drops just start / stop, so one stray
    # token read past the decoder's table and crashed the GPU (af_alloy with a Greek sentence, test-results C25)
    _drop = mtl.drop_invalid_tokens
    mtl.drop_invalid_tokens = lambda x: (t := _drop(x))[t < 6561]
    model, kw = ChatterboxMultilingualTTS.from_pretrained(device=dev), {"language_id": lang}
built_in = model.conds
if job.get("prompt"):
    model.prepare_conditionals(job["prompt"])  # once for all sentences
prompts = job.get("prompts")  # or one reference per text (the voice samples: every voice in one run); null = built-in voice
out = Path(job["out_dir"])
out.mkdir(parents=True, exist_ok=True)
torch.manual_seed(0)  # both sample tokens (temperature 0.8): fixed seed keeps reruns identical
for i, text in enumerate(job["texts"]):
    if prompts:
        model.prepare_conditionals(prompts[i]) if prompts[i] else setattr(model, "conds", built_in)
    wav = model.generate(text, **kw)
    sf.write(out / f"{i}.wav", wav.squeeze(0).cpu().numpy(), model.sr)
print(json.dumps({"sr": model.sr}))
