"""C17 / T-05-T-06: error-propagation study against a reference ("teacher") for each stage.

    python scripts/eval_propagation.py work/<clip>.<src>-<tgt> <reference.json>

reference.json = [{start, end, src, tgt}] on the source timeline: a human transcript + translation
(e.g. data/fleurs_ko_kr.ref.json from scripts/make_fleurs_clip.py) or a teacher system's output.
Writes work/<clip>/propagation.json and prints a per-sentence table.

Runs (oracle substitution):
  A  our transcript  -> our translation      (what the user got)
  B  reference transcript -> our translation (same translator, perfect recognition)
  B - A  = what our speech recognition errors cost the translation
  100 - B = how far our translator is from the reference translation by itself
  TTS    = our dub re-transcribed vs the text it was asked to say (word error rate)
Metric: chrF (sacrebleu), 0-100. It measures character overlap with the reference, not meaning;
treat sentence-level differences under ~10 points as noise.
"""
import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

import sacrebleu

from dubbe import config, device, read_json, translate, write_json
from dubbe.propagation import align, blame, cer, wer


def translate_texts(texts: list[str], cfg: dict) -> list[str]:
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        write_json(d / "segments.json", {"segments": [{"id": i, "start": 0, "end": 0, "src_text": t, "tgt_text": None,
                                                       "edited": False} for i, t in enumerate(texts, 1)]})
        translate.run(None, d, cfg)
        return [s["tgt_text"] for s in read_json(d / "segments.json")["segments"]]


def tts_wer(work: Path, cfg: dict, segs: list[dict]) -> float:
    import torch  # noqa: F401 - CUDA DLLs for ctranslate2 on Windows
    from faster_whisper import WhisperModel

    dev = device()
    model = WhisperModel("large-v3-turbo", device=dev, compute_type="float16" if dev == "cuda" else "int8")
    out, _ = model.transcribe(str(work / "dub.wav"), language=cfg["tgt"]["whisper"], vad_filter=False,
                              condition_on_previous_text=False)
    return wer(" ".join(s.text for s in out), " ".join(s["tgt_text"] or "" for s in segs))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("work", type=Path)
    p.add_argument("reference", type=Path)
    a = p.parse_args()

    data = read_json(a.work / "segments.json")
    segs, ref = data["segments"], json.loads(a.reference.read_text(encoding="utf8"))
    cfg = config.load(data["src"], data["tgt"])
    rows = align(ref, segs)
    b_texts = translate_texts([r["ref"]["src"] for r in rows], cfg)
    for r, tb in zip(rows, b_texts):
        r["cer"] = round(cer(r["src"], r["ref"]["src"]), 3)
        r["chrf_ours"] = round(sacrebleu.sentence_chrf(r["tgt"], [r["ref"]["tgt"]]).score, 1)
        r["tgt_from_ref_transcript"] = tb
        r["chrf_ref_transcript"] = round(sacrebleu.sentence_chrf(tb, [r["ref"]["tgt"]]).score, 1)
        r["blame"] = blame(r["cer"], r["chrf_ours"], r["chrf_ref_transcript"])

    refs = [r["ref"]["tgt"] for r in rows]
    chrf_a = sacrebleu.corpus_chrf([r["tgt"] for r in rows], [refs]).score
    chrf_b = sacrebleu.corpus_chrf(b_texts, [refs]).score
    summary = {
        "reference": str(a.reference), "sentences": len(rows),
        "asr_cer": round(cer(" ".join(r["src"] for r in rows), " ".join(r["ref"]["src"] for r in rows)), 3),
        "chrf_ours": round(chrf_a, 1), "chrf_with_reference_transcript": round(chrf_b, 1),
        "asr_cost_chrf": round(chrf_b - chrf_a, 1), "translation_gap_chrf": round(100 - chrf_b, 1),
        "tts_wer": round(tts_wer(a.work, cfg, segs), 3),
        "timing": {"sped_up": sum((s.get("stretch") or 1) > 1 for s in segs),
                   "overflowing": sum((s.get("overflow") or 0) > cfg["max_overflow"] for s in segs)},
        "blame": dict(Counter(r["blame"] for r in rows)),
    }
    write_json(a.work / "propagation.json", {"summary": summary, "sentences": rows})

    print(f"{'#':>2} {'CER':>5} {'chrF A':>6} {'chrF B':>6}  blame              our translation")
    for i, r in enumerate(rows, 1):
        print(f"{i:>2} {r['cer']:5.2f} {r['chrf_ours']:6.1f} {r['chrf_ref_transcript']:6.1f}  {r['blame']:<18} {r['tgt'][:70]}")
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
