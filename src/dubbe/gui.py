"""Minimal local web page for trying DUBBE: upload a video, pick languages, get the dub.

    dubbe-gui            (or: python -m dubbe.gui)  ->  opens http://127.0.0.1:7860

Runs the normal `dubbe` command underneath, so results land in work/ exactly as from the CLI.
Local only: nothing is shared or uploaded anywhere.
"""
import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

import gradio as gr
import yaml

from . import read_json
from .report import stats_html

LANGS = [k for k in yaml.safe_load((Path(__file__).parent / "languages.yaml").read_text(encoding="utf8")) if k != "defaults"]
UPLOADS = Path("data/uploads")


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

    work = Path("work") / f"{clip.stem}.{src}-{tgt}"
    segs = read_json(work / "segments.json")["segments"]
    rows = [[s["id"], f"{s['start']:.1f}", s["src_text"], s["tgt_text"], ", ".join(s.get("flag") or []) or "-"] for s in segs]
    yield log + "\nDone.", str(work / "dubbed.mp4"), rows, str(work / "report.html"), stats_html(read_json(work / "stats.json"))


def main() -> None:
    with gr.Blocks(title="DUBBE") as page:
        gr.Markdown("## DUBBE — dub a video\nUpload a video, choose the languages, press **Dub**. "
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
        stats = gr.HTML(label="Stats")
        table = gr.Dataframe(headers=["#", "Start (s)", "Source", "Translation", "Check"], wrap=True,
                             label="Sentences — 'Check' marks what a reviewer should look at")
        go.click(dub, [video, src, tgt, keep_bg, slow, force], [log, out, table, report, stats])
    page.launch(inbrowser=True)  # 127.0.0.1 only; share=False by default


if __name__ == "__main__":
    main()
