import html
from collections import Counter
from pathlib import Path

from . import read_json, video_duration, write_json

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


def cost(compute_s: float, video_s: float, c: dict) -> dict:
    """Money: local electricity (upper bound: GPU at full power the whole run), the same run on a
    rented cloud GPU, and a commercial dubbing service for the same minutes. Prices are the
    assumptions in languages.yaml `cost:`; no API is called, so no per-token charges."""
    hours, minutes = compute_s / 3600, video_s / 60
    elec = hours * c["gpu_watts"] / 1000 * c["electricity_usd_per_kwh"]
    cloud = hours * c["cloud_gpu_usd_per_hour"]
    lo, hi = c["elevenlabs_usd_per_min"]
    return {"electricity": round(elec, 4), "cloud_gpu": round(cloud, 4), "api_charges": 0.0,
            "per_video_minute": {"electricity": round(elec / minutes, 4), "cloud_gpu": round(cloud / minutes, 4)},
            "elevenlabs_same_video": [round(minutes * lo, 2), round(minutes * hi, 2)]}


def stats(video: Path, work: Path, data: dict, cfg: dict) -> dict:
    segs, run = data["segments"], read_json(work / "run.json")["done"]
    video_s = video_duration(video)
    compute_s = sum(run.values())
    tok = [s["mt_tokens"] for s in segs if s.get("mt_tokens")]
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
    return {
        "video_seconds": round(video_s, 1),
        "output_seconds": round(video_duration(work / "dubbed.mp4"), 1),
        "processing_seconds": {**run, "total": round(compute_s, 1)},  # last run of each stage
        "seconds_per_video_minute": round(compute_s / (video_s / 60), 1),
        "sentences": len(segs),
        "source_words": sum(len(s["src_text"].split()) for s in segs),
        "translation_tokens": {"in": sum(t[0] for t in tok), "out": sum(t[1] for t in tok)},
        "tts_characters": sum(len(s["tgt_text"] or "") for s in segs),
        "review": {"flagged": sum(bool(s["flag"]) for s in segs), **Counter(f for s in segs for f in s["flag"])},
        "mean_asr_conf": mean([s["asr_conf"] for s in segs if s.get("asr_conf") is not None]),
        "mean_mt_conf": mean([s["mt_conf"] for s in segs if s.get("mt_conf") is not None]),
        "timing": {"sped_up": sum((s.get("stretch") or 1) > 1 for s in segs),
                   "max_speed_up": max((s.get("stretch") or 1) for s in segs) if segs else 1,
                   "picture_slowed": sum((s.get("slow") or 1) > 1 for s in segs),
                   "shortened": sum(bool(s.get("shortened")) for s in segs)},
        "voice": data.get("speakers", {}).get("S1", {}).get("voice"),
        "dub_gain_db": data.get("dub_gain_db"),
        "cost_usd": cost(compute_s, video_s, cfg["cost"]),
    }


def _t(sec: float) -> str:
    return f"{int(sec // 60)}:{sec % 60:04.1f}"


def _row(s: dict) -> str:
    e = html.escape
    cls = ' class="flag"' if s["flag"] else ""
    reasons = ", ".join(f"{STAGE[f]}" for f in s["flag"]) or "—"
    return (f"<tr{cls}><td>{s['id']}</td><td>{_t(s['start'])}</td><td>{e(s['src_text'])}</td>"
            f"<td>{e(s['tgt_text'] or '')}{' ✎' if s['edited'] else ''}</td><td>{s['asr_conf']}</td><td>{s.get('mt_conf')}</td>"
            f"<td>{s['stretch']}×</td><td>{reasons}</td><td><audio controls preload=none src='tts/{s['id']}.wav'></audio></td></tr>")


def stats_html(st: dict) -> str:
    c, p = st["cost_usd"], st["processing_seconds"]
    rows = [("Video", f"{_t(st['video_seconds'])} in → {_t(st['output_seconds'])} out"),
            ("Processing time", f"{p['total']} s ({st['seconds_per_video_minute']} s per minute of video) — "
                                + ", ".join(f"{k} {v} s" for k, v in p.items() if k != "total")),
            ("Work done", f"{st['sentences']} sentences, {st['source_words']} source words, "
                          f"{st['translation_tokens']['in']} → {st['translation_tokens']['out']} translation tokens, "
                          f"{st['tts_characters']} characters spoken"),
            ("Confidence (mean)", f"ASR {st['mean_asr_conf']}, translation {st['mean_mt_conf']}"),
            ("Timing", f"{st['timing']['sped_up']} sped up (max {st['timing']['max_speed_up']}×), "
                       f"{st['timing']['picture_slowed']} with picture slowed, {st['timing']['shortened']} shortened"),
            ("Voice", f"{st['voice']}, loudness adjusted {st['dub_gain_db']} dB"),
            ("Cost (USD)", f"electricity ≤ ${c['electricity']} · same run on a rented cloud GPU ${c['cloud_gpu']} · "
                           f"API charges $0 (all local) · ElevenLabs for this video ${c['elevenlabs_same_video'][0]}–"
                           f"{c['elevenlabs_same_video'][1]} <small>(price assumptions in languages.yaml)</small>")]
    return "<table>" + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows) + "</table>"


def run(video: Path, work: Path, cfg: dict) -> None:
    data = read_json(work / "segments.json")
    segs = data["segments"]
    for s in segs:
        s["flag"] = flags(s, cfg)
    write_json(work / "segments.json", data)
    st = stats(video, work, data, cfg)
    write_json(work / "stats.json", st)

    flagged = [s for s in segs if s["flag"]]
    by_stage = {st_: sum(any(STAGE[f] == st_ for f in s["flag"]) for s in segs) for st_ in STAGE.values()}
    head = "<tr><th>#</th><th>Time</th><th>Source</th><th>Translation</th><th>ASR conf</th><th>MT conf</th><th>Stretch</th><th>Check</th><th>Audio</th></tr>"
    page = f"""<!doctype html><meta charset="utf-8"><title>DUBBE review — {html.escape(video.name)}</title>
<style>body{{font:14px system-ui;margin:24px;max-width:1200px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:6px;vertical-align:top;text-align:left}}tr.flag{{background:#fff4d6}}audio{{width:160px}}</style>
<h1>Review: {html.escape(video.name)} ({data['src']} → {data['tgt']})</h1>
<p><b>{len(flagged)} of {len(segs)} segments to check</b> —
{', '.join(f'{st_}: {n}' for st_, n in by_stage.items())}. Video: <a href="dubbed.mp4">dubbed.mp4</a></p>
{''.join(f"<p>Voice for {k}: <b>{html.escape(v['voice'])}</b> — speaker median pitch {v['median_f0']} Hz, {v['register']} register"
         f"{' (set by reviewer)' if v['override'] else ' (auto; may be wrong for excited speech or several speakers — to change: set voice and override: true in segments.json, run --from tts)'}</p>"
         for k, v in data.get('speakers', {}).items())}
<p>To fix a segment: edit <code>tgt_text</code> in <code>segments.json</code>, set <code>"edited": true</code>,
then run <code>dubbe {html.escape(video.name)} --src {data['src']} --tgt {data['tgt']} --from tts</code>.</p>
<h2>Stats</h2>{stats_html(st)}
<h2>Segments to check</h2><table>{head}{''.join(map(_row, flagged)) or '<tr><td colspan=9>None</td></tr>'}</table>
<details><summary><h2 style="display:inline">All segments</h2></summary><table>{head}{''.join(map(_row, segs))}</table></details>
"""
    (work / "report.html").write_text(page, encoding="utf8")
