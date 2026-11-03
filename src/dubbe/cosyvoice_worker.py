"""Runs CosyVoice 3 (Fun-CosyVoice3-0.5B, Apache-2.0) in .venv-cosyvoice: it pins torch 2.3 / numpy 1.26.
stdin: {"repo": path to the CosyVoice code, "model": hf id, "items": [{text, instruct, prompt_wav, out}]}.
Each item is spoken in the voice of prompt_wav; `instruct` (e.g. "Please speak sadly.") sets the delivery, without it
the text is read plainly. Writes each `out` wav and prints {"sample_rate": n} when done."""
import json
import os
import sys

job = json.load(sys.stdin)
sys.path[:0] = [job["repo"], os.path.join(job["repo"], "third_party", "Matcha-TTS")]

import torch  # noqa: E402
import torchaudio  # noqa: E402
from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402
from huggingface_hub import snapshot_download  # noqa: E402

model = AutoModel(model_dir=snapshot_download(job["model"]))
for it in job["items"]:
    if it.get("instruct"):
        gen = model.inference_instruct2(it["text"], f"You are a helpful assistant. {it['instruct']}<|endofprompt|>",
                                        it["prompt_wav"], stream=False)
    else:
        gen = model.inference_cross_lingual(f"You are a helpful assistant.<|endofprompt|>{it['text']}", it["prompt_wav"],
                                            stream=False)
    torchaudio.save(it["out"], torch.cat([g["tts_speech"] for g in gen], dim=1), model.sample_rate)
print(json.dumps({"sample_rate": model.sample_rate}))
