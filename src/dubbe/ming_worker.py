"""Runs Ming-3.0-tts-0.5B (MIT) in .venv-ming: it pins torch 2.6 / transformers 4.46.
stdin: {"repo": path to the Ming code, "model": hf id, "items": [{text, instruct, prompt_wav, out}]}.
Each item is spoken in the voice of prompt_wav with the emotion `instruct` (Ming's own value: 高兴, 悲伤, 愤怒 ...);
without it 中性 (neutral). Ming's EMOTION task needs no transcript of the reference, so clones work the same way."""
import json
import sys

job = json.load(sys.stdin)
sys.path.insert(0, job["repo"])

import soundfile as sf  # noqa: E402
from ming_tts import MingTTS  # noqa: E402

model = MingTTS(job["model"], text_normalization=False)  # Korean numbers are written out by DUBBE (korean.read_numbers)
for it in job["items"]:
    if not it["text"].strip():  # nothing to say
        sf.write(it["out"], [0.0], 44100)
        continue
    model.synthesize(task="EMOTION", text=it["text"], controls={"emotion": it.get("instruct") or "中性"},
                     prompt_wav_path=it["prompt_wav"], use_spk_emb=True, output_path=it["out"])
