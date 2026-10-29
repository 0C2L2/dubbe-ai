import math
from pathlib import Path

from . import device, free_gpu, read_json, write_json

# NLLB-200 3.3B (CC BY-NC 4.0) in int8 for CTranslate2, the engine faster-whisper already uses: 3.4 GB on disk, ~3.5 GB of
# GPU memory. Against the distilled 600M it scored 3-4 chrF++ higher on TED talks, everyday sentences and FLEURS, in both
# directions, and fixed "Newt Churchill" and "below sea level" (test-results C23). The int8 conversion is not Meta's own:
# CTranslate2 reads its weights in C++ (no Python code from the download runs); the tokenizer is Meta's.
MODEL = "KomorebiAI/nllb-200-3.3B-int8-ct2"
TOKENIZER = "facebook/nllb-200-3.3B"
N_ALTS = 4


def run(video: Path, work: Path, cfg: dict) -> None:
    import ctranslate2
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    data = read_json(work / "segments.json")
    todo = [s for s in data["segments"] if not s["edited"]]  # human edits always win
    dev = device()
    tok = AutoTokenizer.from_pretrained(TOKENIZER, src_lang=cfg["src"]["nllb"])
    tr = ctranslate2.Translator(snapshot_download(MODEL), device=dev, compute_type="int8_float16" if dev == "cuda" else "int8")
    src = [tok.convert_ids_to_tokens(tok.encode(s["src_text"])) for s in todo]
    # N best beams per sentence: the best is used, the rest let the shorten stage pick a shorter wording. The score is the
    # log-probability divided by the length (length_penalty 1, the default), so exp() is the confidence as before: the
    # mean token probability, 0..1
    res = tr.translate_batch(src, target_prefix=[[cfg["tgt"]["nllb"]]] * len(src), beam_size=8, num_hypotheses=N_ALTS,
                             return_scores=True, max_batch_size=16, max_decoding_length=256) if src else []
    for s, toks, r in zip(todo, src, res):
        alts = {}
        for hyp, score in zip(r.hypotheses, r.scores):
            text = tok.decode(tok.convert_tokens_to_ids(hyp[1:]), skip_special_tokens=True).strip()  # [1:]: the language token
            alts.setdefault(text, round(math.exp(score), 3))
        s["alts"] = [{"text": t, "conf": c} for t, c in sorted(alts.items(), key=lambda x: -x[1])]
        s["tgt_text"] = s["alts"][0]["text"]
        s["mt_conf"] = s["alts"][0]["conf"]
        # tokens processed (nothing is billed: the model runs locally), for the stats / API comparison
        s["mt_tokens"] = [len(toks), len(tok(s["tgt_text"])["input_ids"])]

    del tr
    free_gpu()
    write_json(work / "segments.json", data)
