"""Minimal local web page for trying DUBBE.

    dubbe-gui            (or: python -m dubbe.gui)  ->  opens http://127.0.0.1:7860

Tab "Dub": upload a video, pick languages, get the dub (runs the normal `dubbe` command underneath).
Tab "Review & rate": the dubbed video with a coloured timeline of doubtful sentences; click a block,
mark what is wrong and score it (C16). Local only: nothing is shared or uploaded anywhere.
"""
import filecmp
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import gradio as gr
import yaml

from . import read_json, ratings, segment, tags, video_duration, write_json
from .report import STAGE, stats_html, timeline_html

LANGS = [k for k in yaml.safe_load((Path(__file__).parent / "languages.yaml").read_text(encoding="utf8")) if k != "defaults"]
UPLOADS, WORK = Path("data/uploads"), Path("work")


def dubbed_videos() -> list[str]:
    return sorted(p.parent.name for p in WORK.glob("*/dubbed.mp4") if (p.parent / "segments.json").exists())


def dub(video, src, tgt, keep_bg, slow, force):
    if not video:
        raise gr.Error("Upload a video first.")
    if src == tgt:
        raise gr.Error("Source and target language are the same.")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    clip = UPLOADS / Path(video).name
    if clip.exists() and not filecmp.cmp(video, clip, shallow=False):
        force = True  # same name, different video: cached stages would be wrong
    if not clip.exists() or force:
        shutil.copy(video, clip)

    cmd = [sys.executable, "-m", "dubbe.cli", str(clip), "--src", src, "--tgt", tgt]
    cmd += [] if keep_bg else ["--no-background"]
    cmd += ["--slow-video", str(slow)] if slow > 1 else []
    cmd += ["--force"] if force else []
    log = "$ dubbe " + " ".join(cmd[3:]) + "\n"
    yield log, None, None, None, None
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf8",
                            errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf8"})
    for line in proc.stdout:
        if line.strip() and "warn" not in line.lower():  # keep the log readable
            log += line
            yield log, None, None, None, None
    if proc.wait() != 0:
        yield log + "\nFAILED - see the log above.", None, None, None, None
        return

    work = WORK / f"{clip.stem}.{src}-{tgt}"
    segs = read_json(work / "segments.json")["segments"]
    rows = [[s["id"], f"{s['start']:.1f}", s["src_text"], s["tgt_text"], ", ".join(s.get("flag") or []) or "-"] for s in segs]
    yield (log + "\nDone. Open the 'Review & rate' tab to check it.", str(work / "dubbed.mp4"), rows,
           str(work / "report.html"), stats_html(read_json(work / "stats.json")))


# ---------- Review & rate (C11 timeline + C16 ratings) ----------

def _segs(name: str) -> list[dict]:
    return read_json(WORK / name / "segments.json")["segments"]


def _summary(name: str) -> str:
    s = ratings.summarize(ratings.load(WORK / name), _segs(name))
    b = s["blind"]
    txt = (f"**Ratings so far:** {s['ratings']} from {s['raters']} rater(s), {s['sentences_rated']} sentences, "
           f"mean score {s['mean_score']}. Blind (flags hidden): {b['sentences']} sentences, {b['bad']} bad; "
           f"flag precision {b['flag_precision']}, recall {b['flag_recall']}.")
    if "agreement" in s:
        txt += f" Rater agreement: {s['agreement']['percent']} % (kappa {s['agreement']['kappa']}, {s['agreement']['pairs']} pairs)."
    return txt


def load_review(name, hide):
    if not name:
        return "", ""
    total = video_duration(WORK / name / "dubbed.mp4")
    src = "/gradio_api/file=" + (WORK / name / "dubbed.mp4").resolve().as_posix()
    return timeline_html(_segs(name), total, src, show_flags=not hide), _summary(name)


def show_sentence(name, sid, hide):
    s = next((s for s in _segs(name) if s["id"] == sid), None) if name and sid else None
    if not s:
        return "Click a block on the timeline (or type a sentence number).", [], ""
    check = ", ".join(STAGE[f] for f in s.get("flag") or []) or "OK"
    missing = f"\n\n*Not performed by this voice:* {', '.join(s['tags_not_performed'])}" if s.get("tags_not_performed") else ""
    return (f"**Sentence {s['id']}**\n\n*Original:* {s['src_text']}\n\n*Dub:* {s['tgt_text']}"
            + ("" if hide else f"\n\n*DUBBE's check:* {check}") + missing), s.get("tags") or [], s["tgt_text"] or ""


def save_changes(name, sid, text, chosen):
    """Save the reviewer's corrected dub text (marked as a human edit, never re-translated) and tags."""
    if not name or not sid:
        raise gr.Error("Pick a video and a sentence first.")
    data = read_json(WORK / name / "segments.json")
    s = next((s for s in data["segments"] if s["id"] == sid), None)
    if not s:
        raise gr.Error(f"There is no sentence {sid}.")
    edited = segment.edit(s, text, chosen)
    write_json(WORK / name / "segments.json", data)
    return (f"Sentence {int(sid)}: {'text corrected, ' if edited else ''}tags {' '.join('[' + t + ']' for t in s['tags']) or 'none'}. "
            "Press 'Re-dub with my changes' to hear it.")


def redub(name, hide):
    """Re-run from speech synthesis with the reviewer's tags (and any edited text), same options as before."""
    if not name:
        raise gr.Error("Pick a video first.")
    run, data = read_json(WORK / name / "run.json"), read_json(WORK / name / "segments.json")
    if "video" not in run or not Path(run["video"]).exists():
        raise gr.Error("The original video for this dub was not found; run it once from the Dub tab or the command line.")
    opt = run.get("options", {})
    cmd = [sys.executable, "-m", "dubbe.cli", run["video"], "--src", data["src"], "--tgt", data["tgt"], "--from", "tts"]
    cmd += ["--slow-video", str(opt["slow_video"])] if opt.get("slow_video", 1) > 1 else []
    cmd += ["--no-background"] if opt.get("no_background") else []
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf8"})
    if p.returncode != 0:
        raise gr.Error("Re-dub failed: " + (p.stdout + p.stderr).strip().splitlines()[-1])
    timeline, summary = load_review(name, hide)
    return timeline, "Re-dubbed. " + summary


def save_rating(name, rater, sid, errors, score, comment, hide):
    if not name or not sid:
        raise gr.Error("Pick a video and a sentence first.")
    if not rater.strip():
        raise gr.Error("Enter your name or initials, so ratings from different people can be compared.")
    if sid not in {s["id"] for s in _segs(name)}:
        raise gr.Error(f"There is no sentence {sid}.")
    ratings.save(WORK / name, rater.strip(), int(sid), score, errors, comment, hide)
    return f"Saved sentence {int(sid)}. " + _summary(name), [], 80, ""


def random_unrated(name, rater):
    done = {r["id"] for r in ratings.load(WORK / name) if r["rater"] == rater.strip()} if name else set()
    left = [s["id"] for s in _segs(name) if s["id"] not in done] if name else []
    if not left:
        raise gr.Error("Nothing left to rate for this rater.")
    return random.choice(left)


def main() -> None:
    with gr.Blocks(title="DUBBE") as page:
        gr.Markdown("## DUBBE — dub a video, then review it")
        with gr.Tab("Dub"):
            gr.Markdown("Upload a video, choose the languages, press **Dub**. "
                        "The first run downloads models (~5 GB); later runs take about a minute per few minutes of video.")
            with gr.Row():
                with gr.Column():
                    video = gr.Video(label="Original video", sources=["upload"])
                    with gr.Row():
                        src = gr.Dropdown(LANGS, value="ko", label="From")
                        tgt = gr.Dropdown(LANGS, value="en", label="To")
                    keep_bg = gr.Checkbox(True, label="Keep background sound (music, effects)")
                    slow = gr.Slider(1.0, 1.3, value=1.0, step=0.05, label="Allow slowing the picture (1.0 = off)")
                    force = gr.Checkbox(False, label="Re-run every stage (ignore saved results)")
                    go = gr.Button("Dub", variant="primary")
                with gr.Column():
                    out = gr.Video(label="Dubbed video")
                    report = gr.File(label="Review report (report.html)")
                    log = gr.Textbox(label="Progress", lines=12, max_lines=12, autoscroll=True)
            stats = gr.HTML()
            table = gr.Dataframe(headers=["#", "Start (s)", "Source", "Translation", "Check"], wrap=True,
                                 label="Sentences — 'Check' marks what a reviewer should look at")
            go.click(dub, [video, src, tgt, keep_bg, slow, force], [log, out, table, report, stats])

        with gr.Tab("Review & rate"):
            with gr.Row():
                pick = gr.Dropdown(dubbed_videos(), label="Dubbed video", scale=3)
                refresh = gr.Button("Refresh list", scale=1)
                hide = gr.Checkbox(False, label="Evaluation mode: hide DUBBE's flags (use this for ratings you report)", scale=3)
            timeline = gr.HTML()
            with gr.Row():
                with gr.Column(scale=2):
                    rater = gr.Textbox(label="Your name or initials")
                    seg = gr.Number(label="Sentence # (click a block on the timeline)", precision=0, elem_id="seg_pick")
                    info = gr.Markdown()
                    nxt = gr.Button("Random sentence I have not rated")
                with gr.Column(scale=3):
                    errs = gr.CheckboxGroup(ratings.ERRORS, label="What is wrong? (leave empty if nothing)")
                    score = gr.Slider(0, 100, value=80, step=5, label="Overall quality of this dubbed sentence (0 = useless, 100 = perfect)")
                    comment = gr.Textbox(label="Comment (optional)")
                    save = gr.Button("Save rating", variant="primary")
            fix = gr.Textbox(label="Correct the dub text for this sentence (saved as a human edit; never re-translated)", lines=2)
            with gr.Row():
                tagbox = gr.CheckboxGroup(
                    tags.ALL, label="Delivery tags for this sentence — work with every voice: "
                    + ", ".join(f"[{t}] {d}" for t, d in tags.DELIVERY.items())
                    + ". Vocal tags (" + ", ".join(f"[{t}]" for t in tags.VOCAL) + ") and [question] need an expressive voice: for English the "
                    "whole video then switches to Chatterbox's built-in voice (if installed); tags it cannot do are listed as not performed.", scale=4)
                with gr.Column(scale=1):
                    save_tag = gr.Button("Save text & tags")
                    redo = gr.Button("Re-dub with my changes", variant="primary")
            summary = gr.Markdown()

            refresh.click(lambda: gr.update(choices=dubbed_videos()), None, pick)
            page.load(load_review, [pick, hide], [timeline, summary])  # the pre-selected video fires no change event
            pick.change(load_review, [pick, hide], [timeline, summary])
            hide.change(load_review, [pick, hide], [timeline, summary]).then(show_sentence, [pick, seg, hide], [info, tagbox, fix])
            seg.change(show_sentence, [pick, seg, hide], [info, tagbox, fix])
            save_tag.click(save_changes, [pick, seg, fix, tagbox], summary)
            redo.click(redub, [pick, hide], [timeline, summary])
            nxt.click(random_unrated, [pick, rater], seg)
            save.click(save_rating, [pick, rater, seg, errs, score, comment, hide], [summary, errs, score, comment])
    # serve work/ so the review tab can play dubbed videos; still 127.0.0.1 only, share=False by default
    page.launch(inbrowser=True, allowed_paths=[str(WORK.resolve())])


if __name__ == "__main__":
    main()
