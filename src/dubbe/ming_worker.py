"""Runs Ming-3.0-tts-0.5B (MIT) in .venv-ming: it pins torch 2.6 / transformers 4.46.
stdin: {"repo": path to the Ming code, "model": hf id, "items": [{text, instruct, prompt_wav, out}]}.
Each item is spoken in the voice of prompt_wav with the emotion `instruct` (Ming's own value: 高兴, 悲伤, 愤怒 ...);
without it 中性 (neutral). Ming's EMOTION task needs no transcript of the reference, so clones work the same way."""
import json
import sys

job = json.load(sys.stdin)
sys.path.insert(0, job["repo"])

import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from ming_tts import MingTTS  # noqa: E402


def graphed(fn):
    """Ming's flow head (10 steps of a small DiT for every audio patch) replayed as a CUDA graph: Python launched its
    thousands of small kernels while the GPU waited (21-26 % busy at 8 W). Same audio to the sample, 2.6x faster (C60)."""
    graphs = {}

    def run(x, t, c, latent_history, patch_size):
        key = (x.shape, c.shape, latent_history.shape, x.dtype, patch_size)
        if key not in graphs:
            static = [x.clone(), t.clone(), c.clone(), latent_history.clone()]
            side = torch.cuda.Stream()
            side.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(side):  # warm up outside the graph (CUDA's rule for capture)
                for _ in range(2):
                    fn(*static, patch_size)
            torch.cuda.current_stream().wait_stream(side)
            g = torch.cuda.CUDAGraph()
            with torch.cuda.graph(g):
                out = fn(*static, patch_size)
            graphs[key] = (g, static, out)
        g, static, out = graphs[key]
        for dst, src in zip(static, (x, t, c, latent_history)):
            dst.copy_(src)
        g.replay()
        return out.clone()
    return run


model = MingTTS(job["model"], text_normalization=False)  # Korean numbers are written out by DUBBE (korean.read_numbers)
if torch.cuda.is_available():
    dit = model.model.flowloss.cfm.model
    dit.forward_with_cfg = graphed(dit.forward_with_cfg)
for it in job["items"]:
    if not it["text"].strip():  # nothing to say
        sf.write(it["out"], [0.0], 44100)
        continue
    model.synthesize(task="EMOTION", text=it["text"], controls={"emotion": it.get("instruct") or "中性"},
                     prompt_wav_path=it["prompt_wav"], use_spk_emb=True, output_path=it["out"])
