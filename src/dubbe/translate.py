from pathlib import Path

from . import device, free_gpu, read_json, write_json

MODEL = "facebook/nllb-200-distilled-600M"
N_ALTS = 4
BATCH = 8  # sentences per generate call


def confidence(model, inputs, seqs, pad_id: int, chunk: int = 8) -> list[float]:
    """Mean per-token probability of each generated sequence (length-normalised, 0..1),
    from one teacher-forced forward pass. generate(output_scores=True) would give the same
    number but keeps a 256k-vocab score table per beam per step and ran out of 8 GB GPU memory."""
    import torch

    rep = {k: v.repeat_interleave(len(seqs) // len(inputs["input_ids"]), 0) for k, v in inputs.items()}
    out = []
    for i in range(0, len(seqs), chunk):
        dec, labels = seqs[i:i + chunk, :-1], seqs[i:i + chunk, 1:]
        with torch.no_grad():
            logits = model(**{k: v[i:i + chunk] for k, v in rep.items()}, decoder_input_ids=dec).logits
        lp = logits.float().log_softmax(-1).gather(-1, labels.unsqueeze(-1)).squeeze(-1)
        mask = labels != pad_id
        out += ((lp * mask).sum(1) / mask.sum(1)).exp().tolist()
    return out


def run(video: Path, work: Path, cfg: dict) -> None:
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    data = read_json(work / "segments.json")
    todo = [s for s in data["segments"] if not s["edited"]]  # human edits always win
    dev = device()
    tok = AutoTokenizer.from_pretrained(MODEL, src_lang=cfg["src"]["nllb"])
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL).to(dev)
    tgt_id = tok.convert_tokens_to_ids(cfg["tgt"]["nllb"])

    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        inputs = tok([s["src_text"] for s in batch], return_tensors="pt", padding=True).to(dev)
        # N best beams per sentence: the best is used, the rest let the shorten stage pick a shorter wording
        seqs = model.generate(**inputs, forced_bos_token_id=tgt_id, num_beams=8, num_return_sequences=N_ALTS)
        texts = tok.batch_decode(seqs, skip_special_tokens=True)
        confs = confidence(model, inputs, seqs, tok.pad_token_id)
        for k, s in enumerate(batch):
            alts = {}
            for text, c in zip(texts[k * N_ALTS:(k + 1) * N_ALTS], confs[k * N_ALTS:(k + 1) * N_ALTS]):
                alts.setdefault(text.strip(), round(c, 3))
            s["alts"] = [{"text": t, "conf": c} for t, c in sorted(alts.items(), key=lambda x: -x[1])]
            s["tgt_text"] = s["alts"][0]["text"]
            s["mt_conf"] = s["alts"][0]["conf"]
            # tokens processed (nothing is billed: the model runs locally), for the stats / API comparison
            s["mt_tokens"] = [int(inputs["attention_mask"][k].sum()), len(tok(s["tgt_text"])["input_ids"])]

    del model
    free_gpu()
    write_json(work / "segments.json", data)
