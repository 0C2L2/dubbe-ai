import math
import re
from pathlib import Path

from . import read_json, write_json


def _dur(s: list[dict]) -> float:
    return s[-1]["end"] - s[0]["start"]


def _split_long(s: list[dict], max_dur: float, max_words: int) -> list[list[dict]]:
    if len(s) < 2 or (_dur(s) <= max_dur and len(s) <= max_words):
        return [s]
    k = max(range(1, len(s)), key=lambda i: s[i]["start"] - s[i - 1]["end"])  # longest internal pause
    return _split_long(s[:k], max_dur, max_words) + _split_long(s[k:], max_dur, max_words)


def _merge_short(sents: list[list[dict]], min_dur: float) -> list[list[dict]]:
    i = 0
    while i < len(sents) and len(sents) > 1:
        s = sents[i]
        if _dur(s) >= min_dur:
            i += 1
            continue
        gap_prev = s[0]["start"] - sents[i - 1][-1]["end"] if i > 0 else math.inf
        gap_next = sents[i + 1][0]["start"] - s[-1]["end"] if i + 1 < len(sents) else math.inf
        if gap_prev <= gap_next:
            sents[i - 1] = sents[i - 1] + s
        else:
            sents[i + 1] = s + sents[i + 1]
        del sents[i]
    return sents


def group(words: list[dict], cfg: dict) -> list[list[dict]]:
    """Group timed words into translatable sentences (known hard part #1).
    Close on a sentence ending followed by a short pause, or on a long pause alone;
    then split over-long sentences and merge tiny fragments."""
    end_re = re.compile(cfg["src"]["sentence_end"])
    sents, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        pause = words[i + 1]["start"] - w["end"] if i + 1 < len(words) else math.inf
        if pause >= cfg["break_pause"] or (end_re.search(w["w"]) and pause >= cfg["close_pause"]):
            sents.append(cur)
            cur = []
    if cur:
        sents.append(cur)
    sents = [part for s in sents for part in _split_long(s, cfg["max_dur"], cfg["max_words"])]
    return _merge_short(sents, cfg["min_dur"])


def edit(s: dict, text: str, chosen: list[str]) -> bool:
    """A reviewer's change to one sentence: tags as chosen (known ones, fixed order), and the dub text only
    if it changed - then it is marked as a human edit, which later stages never re-translate."""
    from .tags import ALL
    tags = [t for t in ALL if t in chosen]
    if tags != (s.get("tags") or []):
        s["tags_edited"] = True  # the emotion stage never overwrites them again
    s["tags"] = tags
    changed = bool(text.strip()) and text.strip() != (s["tgt_text"] or "").strip()
    if changed:
        s.update(tgt_text=text.strip(), edited=True)
    return changed


def carry_over(old: list[dict], new: list[dict]) -> list[dict]:
    """Copy a reviewer's edited translation and tags from the old sentences to the new ones.
    Re-segmenting renumbers sentences, so match by time: an old sentence carries over to the new one
    when each covers more than half of the other (a split or merge of sentences does not carry edits)."""
    for n in new:
        for o in old:
            ov = min(n["end"], o["end"]) - max(n["start"], o["start"])
            if ov > 0.5 * (n["end"] - n["start"]) and ov > 0.5 * (o["end"] - o["start"]):
                if o.get("edited"):
                    n.update(tgt_text=o["tgt_text"], edited=True)
                if o.get("tags") and (o.get("tags_edited") or "auto_tags" not in o):  # the reviewer's, not heard ones
                    n.update(tags=o["tags"], tags_edited=True)
                break
    return new


def run(video: Path, work: Path, cfg: dict) -> None:
    words = read_json(work / "words.json")["words"]
    join = cfg["src"].get("join", " ")
    segments = []
    for n, s in enumerate(group(words, cfg), 1):
        scores = [w["score"] for w in s if "score" in w]
        segments.append({
            "id": n, "start": s[0]["start"], "end": s[-1]["end"],
            "src_text": join.join(w["w"] for w in s), "tgt_text": None, "edited": False,
            "asr_conf": round(sum(scores) / len(scores), 3) if scores else None, "mt_conf": None,
            "tts_dur": None, "stretch": None, "placed_start": None, "overflow": None, "flag": None,
        })
    old = read_json(work / "segments.json") if (work / "segments.json").exists() else {}
    keep = {"speakers": old["speakers"]} if "speakers" in old else {}  # reviewer voice overrides survive re-runs
    segments = carry_over(old.get("segments", []), segments)  # ...and so do edited translations and tags
    write_json(work / "segments.json", {"src": cfg["src"]["code"], "tgt": cfg["tgt"]["code"], **keep, "segments": segments})
