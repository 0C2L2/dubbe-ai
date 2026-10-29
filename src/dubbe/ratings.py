"""C16: human ratings of single sentences, in the style of Error Span Annotation (WMT 2024):
the rater marks what is wrong, then scores the sentence 0-100. Stored in work/<clip>/ratings.json."""
import datetime as dt
from collections import defaultdict
from pathlib import Path
from statistics import mean

from . import read_json, write_json

ERRORS = ["wrong meaning", "wrong word", "missing words", "mispronounced", "cut off", "bad timing"]


def load(work: Path) -> list[dict]:
    f = work / "ratings.json"
    return read_json(f)["ratings"] if f.exists() else []


def save(work: Path, rater: str, seg_id: int, score: int, errors: list[str], comment: str, flags_hidden: bool) -> list[dict]:
    rs = [r for r in load(work) if not (r["rater"] == rater and r["id"] == seg_id)]  # a rater's latest rating counts
    rs.append({"rater": rater, "id": int(seg_id), "score": int(score), "errors": list(errors), "comment": comment,
               "flags_hidden": bool(flags_hidden), "at": dt.datetime.now().isoformat(timespec="seconds")})
    write_json(work / "ratings.json", {"ratings": rs})
    return rs


def is_bad(r: dict, bad_below: int) -> bool:
    return r["score"] < bad_below or bool(r["errors"])


def summarize(ratings: list[dict], segs: list[dict], bad_below: int = 60) -> dict:
    """Scores, plus - from blind ratings only (flags hidden) - whether DUBBE's flags pick the
    sentences raters found bad (T-07), and agreement between raters on the same sentence."""
    out = {"ratings": len(ratings), "raters": len({r["rater"] for r in ratings}),
           "sentences_rated": len({r["id"] for r in ratings}),
           "mean_score": round(mean(r["score"] for r in ratings), 1) if ratings else None}
    by_id = defaultdict(list)
    for r in ratings:
        if r["flags_hidden"]:
            by_id[r["id"]].append(is_bad(r, bad_below))
    bad = {i for i, v in by_id.items() if sum(v) / len(v) >= 0.5}  # majority of raters; a tie counts as bad
    flagged = {s["id"] for s in segs if s.get("flag")} & set(by_id)
    hit = len(flagged & bad)
    out["blind"] = {"sentences": len(by_id), "bad": len(bad), "flagged": len(flagged),
                    "flag_precision": round(hit / len(flagged), 2) if flagged else None,
                    "flag_recall": round(hit / len(bad), 2) if bad else None}
    pairs = [(v[0], v[1]) for v in by_id.values() if len(v) >= 2]
    if pairs:  # Cohen's kappa on good/bad for the first two raters of each sentence
        po = mean(a == b for a, b in pairs)
        p1, p2 = mean(a for a, _ in pairs), mean(b for _, b in pairs)
        pe = p1 * p2 + (1 - p1) * (1 - p2)
        out["agreement"] = {"pairs": len(pairs), "percent": round(100 * po, 1),
                            "kappa": round((po - pe) / (1 - pe), 2) if pe < 1 else None}
    return out
