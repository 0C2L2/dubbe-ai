import html
from collections import Counter
from pathlib import Path

from . import read_json, video_duration, write_json

# flag -> pipeline stage it points at (demo step 4: which stage caused it)
STAGE = {"low_asr": "ASR", "low_mt": "Translation", "overflow": "Timing"}


def flags(s: dict, cfg: dict) -> list[str]:
    f = []
    # per-language thresholds: confidences differ by language (en->ko median 0.40 vs ko->en 0.53 on our clips)
    min_asr = cfg.get("src", {}).get("min_asr_conf", cfg["min_asr_conf"])
    min_mt = cfg.get("tgt", {}).get("min_mt_conf", cfg["min_mt_conf"])
    if s.get("asr_conf") is not None and s["asr_conf"] < min_asr:
        f.append("low_asr")
    if s.get("mt_conf") is not None and s["mt_conf"] < min_mt:
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
        "voice": data.get("tts_used", {}).get("voice") or data.get("speakers", {}).get("S1", {}).get("voice"),
        "dub_gain_db": data.get("dub_gain_db"),
        "cost_usd": cost(compute_s, video_s, cfg["cost"]),
    }


def _t(sec: float) -> str:
    return f"{int(sec // 60)}:{sec % 60:04.1f}"


COLOR = {"low_mt": "#e5484d", "low_asr": "#f76b15", "overflow": "#e2a336"}  # first flag decides the colour


def placed(s: dict) -> tuple[float, float]:
    """Where a sentence's dub sits on the dubbed video: start and length in seconds (timeline, subtitles)."""
    a = s.get("placed_start") if s.get("placed_start") is not None else s["start"]
    return a, (s.get("tts_dur") or s["end"] - s["start"]) / (s.get("stretch") or 1)


def transcript(segs: list[dict], field: str, speakers: dict | None = None) -> str:
    """Plain transcript, one line per sentence with its time and - when there are several - who says it."""
    names = {k: v.get("name") or k for k, v in (speakers or {}).items()}
    many = len({s.get("speaker", "S1") for s in segs}) > 1
    return "\n".join(f"[{_t(s['start'])}] " + (f"{names.get(s.get('speaker', 'S1'), s.get('speaker', 'S1'))}: " if many else "")
                     + (s.get(field) or "").strip() for s in segs if (s.get(field) or "").strip())


# caption colour per speaker: the BBC subtitle guidelines' order (white, yellow, cyan, green), then four more
CAPTION_COLORS = ["#FFFFFF", "#FFFF00", "#00FFFF", "#00FF00", "#FF80FF", "#FFB040", "#80B0FF", "#FF8080"]
# fonts for burned-in captions, checked on Windows with ffmpeg's libass (Korean, Japanese, Chinese, Arabic, Hindi);
# ponytail: Windows font names - a Linux server needs e.g. Noto Sans CJK here
CAPTION_FONTS = {"ko": "Malgun Gothic", "ja": "Yu Gothic", "zh": "Microsoft YaHei", "hi": "Nirmala UI"}


def speaker_colors(segs: list[dict]) -> dict:
    """Speaker -> caption colour, S1 (who speaks most) white; empty with one speaker (no colours needed)."""
    ids = sorted({s.get("speaker", "S1") for s in segs}, key=lambda k: (len(k), k))
    return {sp: CAPTION_COLORS[i % len(CAPTION_COLORS)] for i, sp in enumerate(ids)} if len(ids) > 1 else {}


def subtitles(segs: list[dict], field: str, vtt: bool = False, speakers: dict | None = None) -> str:
    """SRT or WebVTT. On a dub: where each sentence's dub is placed; on a plain transcript: where it was said.
    With speakers (and more than one of them): each speaker's lines in their colour — SRT <font color> (VLC, many TVs),
    WebVTT a voice tag with a class and a STYLE block (browsers)."""
    def ts(sec: float) -> str:
        h, rest = divmod(round(sec * 1000), 3_600_000)
        m, rest = divmod(rest, 60_000)
        return f"{h:02}:{m:02}:{rest // 1000:02}{'.' if vtt else ','}{rest % 1000:03}"

    colors = speaker_colors(segs) if speakers is not None else {}
    names = {k: (v.get("name") or k) for k, v in (speakers or {}).items()}
    cues = [s for s in segs if (s.get(field) or "").strip()]
    out = ["WEBVTT", ""] if vtt else []
    if vtt and colors:
        out += ["STYLE"] + [f"::cue(.{sp.lower()}) {{ color: {c}; }}" for sp, c in colors.items()] + [""]
    for n, s in enumerate(cues, 1):
        a, d = placed(s)
        text, sp = s[field].strip(), s.get("speaker", "S1")
        if colors:
            text = (f"<v.{sp.lower()} {names.get(sp, sp)}>{text}</v>" if vtt else f'<font color="{colors[sp]}">{text}</font>')
        out += ([] if vtt else [str(n)]) + [f"{ts(a)} --> {ts(a + d)}", text, ""]
    return "\n".join(out)


def ass(segs: list[dict], field: str, speakers: dict | None = None, lang: str = "en") -> str:
    """Advanced SubStation Alpha: one style per speaker in its colour (white with one speaker), for players that read it
    (VLC, mpv) and for burning the captions into the video (ffmpeg's libass)."""
    colors = speaker_colors(segs) or {s.get("speaker", "S1"): CAPTION_COLORS[0] for s in segs}
    names = {k: (v.get("name") or k) for k, v in (speakers or {}).items()}
    font = CAPTION_FONTS.get(lang, "Arial")

    def t(sec: float) -> str:
        cs = round(sec * 100)
        return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"

    def bgr(hex_: str) -> str:  # ASS colours are &H00BBGGRR
        return f"&H00{hex_[5:7]}{hex_[3:5]}{hex_[1:3]}"

    out = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "WrapStyle: 0", "",
           "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
           "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"]
    out += [f"Style: {sp},{font},58,{bgr(c)},&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,90,90,60,1"
            for sp, c in colors.items()]
    out += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for s in segs:
        text = (s.get(field) or "").strip().replace("{", "(").replace("}", ")").replace("\n", r"\N")  # braces are ASS commands
        if text:
            a, d = placed(s)
            sp = s.get("speaker", "S1")
            out.append(f"Dialogue: 0,{t(a)},{t(a + d)},{sp},{names.get(sp, sp).replace(',', ' ')},0,0,0,,{text}")
    return "\n".join(out) + "\n"


def timeline_html(segs: list[dict], total: float, video_src: str, show_flags: bool = True) -> str:
    """C11: video + a bar with one block per sentence on the dubbed video's timeline, coloured by its
    flag (grey when flags are hidden for blind rating). Clicking a block jumps the video there and
    writes the sentence number into an element with id `seg_pick` (the web page's rating form)."""
    blocks = []
    for s in segs:
        a, d = placed(s)
        f = s.get("flag") or []
        color = (COLOR[f[0]] if f else "#30a46c") if show_flags else "#8b8d98"
        why = f" — check: {', '.join(STAGE[x] for x in f)}" if show_flags and f else ""
        tags = f"\ntags: {' '.join('[' + t + ']' for t in s.get('tags') or [])}" if s.get("tags") else ""
        if s.get("tags_not_performed"):
            tags += f" (not performed by this voice: {', '.join(s['tags_not_performed'])})"
        tip = html.escape(f"#{s['id']} at {_t(a)}{why}\n{s['src_text']}\n{s['tgt_text'] or ''}{tags}", quote=True)
        pick = (f"var p=document.querySelector('#seg_pick input');if(p){{p.value={s['id']};"
                f"p.dispatchEvent(new Event('input',{{bubbles:true}}));}}")
        blocks.append(f'<div class="tl-b" title="{tip}" onclick="var v=document.getElementById(\'dubv\');'
                      f'v.currentTime={a:.2f};v.play();{pick}" style="left:{100 * a / total:.3f}%;'
                      f'width:{max(100 * d / total, 0.5):.3f}%;background:{color}">{s["id"]}{" ✦" if s.get("tags") else ""}</div>')
    legend = ("<span style='background:#e5484d'>translation</span><span style='background:#f76b15'>speech recognition</span>"
              "<span style='background:#e2a336'>timing</span><span style='background:#30a46c'>OK</span>"
              if show_flags else "<span style='background:#8b8d98'>flags hidden (blind rating)</span>")
    return f"""<style>.tl{{position:relative;height:34px;background:#eee;border-radius:4px;margin:6px 0}}
.tl-b{{position:absolute;top:3px;height:28px;border-radius:3px;color:#fff;font:11px system-ui;text-align:center;
line-height:28px;cursor:pointer;overflow:hidden;opacity:.9}}.tl-b:hover{{opacity:1;outline:2px solid #000}}
#tl-ph{{position:absolute;top:0;width:2px;height:34px;background:#000;pointer-events:none}}
.tl-leg span{{color:#fff;font:12px system-ui;padding:2px 6px;border-radius:3px;margin-right:6px}}</style>
<video id="dubv" src="{html.escape(video_src, quote=True)}" controls style="width:100%;max-height:480px;background:#000"
 ontimeupdate="document.getElementById('tl-ph').style.left=(100*this.currentTime/{total:.3f})+'%'"></video>
<div class="tl">{''.join(blocks)}<div id="tl-ph"></div></div><div class="tl-leg">{legend}</div>"""


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
{''.join(f"<p>Voice for {html.escape(v.get('name') or k)}: <b>{html.escape(str(v.get('voice')))}</b> — median pitch {v.get('median_f0')} Hz, {v.get('register')} register"
         f"{' (set by reviewer)' if v.get('override') else ' (auto; change it in the review editor, or set voice and override: true in segments.json and run --from tts)'}</p>"
         for k, v in data.get('speakers', {}).items())}
<p>To fix a segment: edit <code>tgt_text</code> in <code>segments.json</code>, set <code>"edited": true</code>,
then run <code>dubbe {html.escape(video.name)} --src {data['src']} --tgt {data['tgt']} --from tts</code>.</p>
<h2>Video — coloured parts need checking (hover for text, click to jump)</h2>{timeline_html(segs, st['output_seconds'], 'dubbed.mp4')}
<h2>Stats</h2>{stats_html(st)}
<h2>Segments to check</h2><table>{head}{''.join(map(_row, flagged)) or '<tr><td colspan=9>None</td></tr>'}</table>
<details><summary><h2 style="display:inline">All segments</h2></summary><table>{head}{''.join(map(_row, segs))}</table></details>
"""
    (work / "report.html").write_text(page, encoding="utf8")
