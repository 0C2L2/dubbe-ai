import html
from pathlib import Path

from . import read_json, write_json

# flag -> pipeline stage it points at (demo step 4: which stage caused it)
STAGE = {"low_asr": "ASR", "low_mt": "Translation", "overflow": "Timing"}


def flags(s: dict, cfg: dict) -> list[str]:
    f = []
    if s.get("asr_conf") is not None and s["asr_conf"] < cfg["min_asr_conf"]:
        f.append("low_asr")
    if s.get("mt_conf") is not None and s["mt_conf"] < cfg["min_mt_conf"]:
        f.append("low_mt")
    if (s.get("overflow") or 0) > cfg["max_overflow"]:
        f.append("overflow")
    return f


def _t(sec: float) -> str:
    return f"{int(sec // 60)}:{sec % 60:04.1f}"


def _row(s: dict) -> str:
    e = html.escape
    cls = ' class="flag"' if s["flag"] else ""
    reasons = ", ".join(f"{STAGE[f]}" for f in s["flag"]) or "—"
    return (f"<tr{cls}><td>{s['id']}</td><td>{_t(s['start'])}</td><td>{e(s['src_text'])}</td>"
            f"<td>{e(s['tgt_text'] or '')}{' ✎' if s['edited'] else ''}</td><td>{s['asr_conf']}</td><td>{s.get('mt_conf')}</td>"
            f"<td>{s['stretch']}×</td><td>{reasons}</td><td><audio controls preload=none src='tts/{s['id']}.wav'></audio></td></tr>")


def run(video: Path, work: Path, cfg: dict) -> None:
    data = read_json(work / "segments.json")
    segs = data["segments"]
    for s in segs:
        s["flag"] = flags(s, cfg)
    write_json(work / "segments.json", data)

    flagged = [s for s in segs if s["flag"]]
    by_stage = {st: sum(any(STAGE[f] == st for f in s["flag"]) for s in segs) for st in STAGE.values()}
    head = "<tr><th>#</th><th>Time</th><th>Source</th><th>Translation</th><th>ASR conf</th><th>MT conf</th><th>Stretch</th><th>Check</th><th>Audio</th></tr>"
    page = f"""<!doctype html><meta charset="utf-8"><title>DUBBE review — {html.escape(video.name)}</title>
<style>body{{font:14px system-ui;margin:24px;max-width:1200px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:6px;vertical-align:top;text-align:left}}tr.flag{{background:#fff4d6}}audio{{width:160px}}</style>
<h1>Review: {html.escape(video.name)} ({data['src']} → {data['tgt']})</h1>
<p><b>{len(flagged)} of {len(segs)} segments to check</b> —
{', '.join(f'{st}: {n}' for st, n in by_stage.items())}. Video: <a href="dubbed.mp4">dubbed.mp4</a></p>
{''.join(f"<p>Voice for {k}: <b>{html.escape(v['voice'])}</b> — speaker median pitch {v['median_f0']} Hz, {v['register']} register"
         f"{' (set by reviewer)' if v['override'] else ' (auto; may be wrong for excited speech or several speakers — to change: set voice and override: true in segments.json, run --from tts)'}</p>"
         for k, v in data.get('speakers', {}).items())}
<p>To fix a segment: edit <code>tgt_text</code> in <code>segments.json</code>, set <code>"edited": true</code>,
then run <code>dubbe {html.escape(video.name)} --src {data['src']} --tgt {data['tgt']} --from tts</code>.</p>
<h2>Segments to check</h2><table>{head}{''.join(map(_row, flagged)) or '<tr><td colspan=9>None</td></tr>'}</table>
<details><summary><h2 style="display:inline">All segments</h2></summary><table>{head}{''.join(map(_row, segs))}</table></details>
"""
    (work / "report.html").write_text(page, encoding="utf8")
