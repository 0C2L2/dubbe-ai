"""C17: where does quality break down? Compare our stage outputs with a reference ("teacher") per stage.

The reference is a JSON list [{start, end, src, tgt}]: a human transcript + translation (gold), or a
teacher system's transcript + translation (e.g. ElevenLabs). Times are on the source video's timeline.
"""
import re


def norm(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _lev(a, b) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def cer(hyp: str, ref: str) -> float:
    """Character error rate without spaces/punctuation (the usual measure for Korean)."""
    h, r = norm(hyp).replace(" ", ""), norm(ref).replace(" ", "")
    return _lev(h, r) / max(len(r), 1)


def wer(hyp: str, ref: str) -> float:
    h, r = norm(hyp).split(), norm(ref).split()
    return _lev(h, r) / max(len(r), 1)


def align(ref: list[dict], segs: list[dict], margin: float = 0.3) -> list[dict]:
    """Our segments whose midpoint falls inside each reference sentence (our sentence boundaries
    differ from the reference's, so several of ours may map to one of theirs)."""
    out = []
    for r in ref:
        mine = [s for s in segs if r["start"] - margin <= (s["start"] + s["end"]) / 2 <= r["end"] + margin]
        out.append({"ref": r, "ids": [s["id"] for s in mine],
                    "src": " ".join(s["src_text"] for s in mine), "tgt": " ".join(s["tgt_text"] or "" for s in mine)})
    return out


def blame(asr_cer: float, chrf_ours: float, chrf_ref_input: float) -> str:
    """Rule of thumb for one sentence: which stage hurt it most.
    chrf_ours = our ASR + our MT; chrf_ref_input = reference transcript + our MT."""
    if asr_cer > 0.15 and chrf_ref_input - chrf_ours > 10:
        return "ASR"
    if chrf_ref_input < 45:
        return "translation"
    if chrf_ours < 45:
        return "ASR + translation"
    return "ok"
