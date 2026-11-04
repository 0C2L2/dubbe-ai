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

# only what CosyVoice 3 loads (cli/cosyvoice.py, no TensorRT): skips llm.rl.pt, the TensorRT .onnx and the batch
# tokenizer - about 4.3 GB never read
NEEDED = ["*.yaml", "*.json", "llm.pt", "flow.pt", "hift.pt", "campplus.onnx", "speech_tokenizer_v3.onnx", "CosyVoice-BlankEN/*",
          "speech_tokenizer_v2.onnx"]  # v2: CosyVoice 2, the base of Navoiy
model = AutoModel(model_dir=snapshot_download(job["model"], allow_patterns=NEEDED))
system = "You are a helpful assistant. "
if job.get("llm"):  # Navoiy TTS (Uzbek, Apache-2.0): CosyVoice 2 with its own LLM weights; it was trained without the system line
    from huggingface_hub import hf_hub_download  # noqa: E402
    state = torch.load(hf_hub_download(*job["llm"]), map_location="cpu", weights_only=True)
    missing = model.model.llm.load_state_dict(state.get("state_dict", state), strict=False).missing_keys
    if missing:
        raise SystemExit(f"{job['llm'][1]}: {len(missing)} LLM weights missing")
    system = ""
for it in job["items"]:
    if not it["text"].strip():  # nothing to say
        torchaudio.save(it["out"], torch.zeros(1, 1), model.sample_rate)
        continue
    if it.get("instruct"):
        gen = model.inference_instruct2(it["text"], f"{system}{it['instruct']}<|endofprompt|>", it["prompt_wav"], stream=False)
    else:
        gen = model.inference_cross_lingual(f"You are a helpful assistant.<|endofprompt|>{it['text']}", it["prompt_wav"],
                                            stream=False)
    torchaudio.save(it["out"], torch.cat([g["tts_speech"] for g in gen], dim=1), model.sample_rate)
print(json.dumps({"sample_rate": model.sample_rate}))
