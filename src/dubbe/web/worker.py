"""Runs waiting dub jobs one at a time with the normal `dubbe` command in a subprocess: the same code as the
command line, and all GPU memory is freed when it exits. Progress is the stage it prints ("[run]  tts ...")."""
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from .. import read_json
from ..cli import STAGES
from . import clones, db

STAGE_NAMES = list(STAGES)
STATE = {"job": None, "proc": None, "beat": 0.0}  # shown on the admin page


def folder(pid: int) -> Path:
    return db.ROOT / "projects" / str(pid)


def video(pid: int) -> Path | None:
    # is_file: the pipeline's work folder next to it is also called video.<src>-<tgt>
    return next((f for f in folder(pid).glob("video.*") if f.is_file()), None)


def work(p) -> Path:
    """The pipeline's own work folder for this project (the CLI names it <video stem>.<src>-<tgt>)."""
    return folder(p["id"]) / f"video.{p['src']}-{p['tgt']}"


def command(p, from_stage: str | None) -> list[str]:
    cmd = [sys.executable, "-m", "dubbe.cli", str(video(p["id"])), "--src", p["src"], "--tgt", p["tgt"],
           "--work", str(folder(p["id"]))]
    cmd += ["--from", from_stage] if from_stage else []
    cmd += [] if p["keep_bg"] else ["--no-background"]
    cmd += ["--slow-video", str(p["slow"])] if p["slow"] > 1 else []
    cmd += ["--voice", p["voice"]] if p["voice"] else []  # chosen at upload; the editor's choice wins later
    return cmd


def run_job(job) -> None:
    p = db.one("select * from projects where id=?", job["project_id"])
    seg_file = work(p) / "segments.json"
    voices = {sp: v.get("voice") for sp, v in ((read_json(seg_file).get("speakers") or {}) if seg_file.exists() else {}).items()}
    voices["S1"] = voices.get("S1") or p["voice"]  # first dub: the voice chosen at upload is the main speaker's
    owner = db.one("select * from users where id=?", p["owner_id"])
    tail, prompts = deque(maxlen=12), []
    try:
        for sp, key in voices.items():  # each speaker's clone recording, for this job only
            prompts.append(work(p) / f"voice_prompt_{sp}.wav")
            if (key or "").startswith("video:"):
                clones.write_speaker_reference(p["id"], key, prompts[-1])  # cloned from this video, with consent
            else:
                clones.write_reference(owner, key, prompts[-1])  # the owner's own clone, or one they got
        proc = subprocess.Popen(command(p, job["from_stage"]), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf8"})
        STATE["proc"] = proc
        for line in proc.stdout:
            if "warn" in line.lower():
                continue
            tail.append(line.rstrip())
            if m := re.match(r"\[run\]\s+(\w+)", line):
                db.run("update jobs set stage=? where id=?", m[1], job["id"])
        ok = proc.wait() == 0
    finally:
        for f in prompts:
            f.unlink(missing_ok=True)
    if ok and seg_file.exists() and (job["from_stage"] or "tts") in STAGE_NAMES[:STAGE_NAMES.index("tts") + 1]:
        data = read_json(seg_file)
        for sp, info in (data.get("speakers") or {}).items():  # uses of library clones, per speaker
            used = (info.get("used") or {}).get("voice")
            if clones.voice_id(used):
                clones.record_use(used, p["owner_id"], sum(len(s["tgt_text"] or "") for s in data["segments"]
                                                           if s.get("speaker", "S1") == sp), "dub")
    db.run("update jobs set status=?, error=?, finished_at=? where id=?",
           "done" if ok else "failed", None if ok else "\n".join(tail), db.now(), job["id"])


def run_task(task) -> None:
    """A tool task (text to speech, speech to text, translate, voice isolator): dubbe.web.tools in its own process."""
    from . import tools
    tools.folder(task["id"]).mkdir(parents=True, exist_ok=True)
    tail = deque(maxlen=12)
    proc = subprocess.Popen([sys.executable, "-m", "dubbe.web.tools", str(task["id"])], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf8", errors="replace",
                            env={**os.environ, "PYTHONIOENCODING": "utf8", "DUBBE_WEB_DATA": str(db.ROOT)})
    STATE["proc"] = proc
    for line in proc.stdout:
        if "warn" not in line.lower():
            tail.append(line.rstrip())
    ok = proc.wait() == 0
    db.run("update tasks set status=?, error=?, finished_at=? where id=?",
           "done" if ok else "failed", None if ok else "\n".join(tail), db.now(), task["id"])


def delete_task(tid: int) -> None:
    from . import tools
    db.run("update tasks set deleted_at=? where id=? and deleted_at is null", db.now(), tid)
    shutil.rmtree(tools.folder(tid), ignore_errors=True)


def run_voice(v) -> None:
    """The consent check of a recorded voice clone (dubbe.web.clones) in its own process, like a tool task."""
    tail = deque(maxlen=12)
    proc = subprocess.Popen([sys.executable, "-m", "dubbe.web.clones", str(v["id"])], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf8", errors="replace",
                            env={**os.environ, "PYTHONIOENCODING": "utf8", "DUBBE_WEB_DATA": str(db.ROOT)})
    STATE["proc"] = proc
    for line in proc.stdout:
        if "warn" not in line.lower():
            tail.append(line.rstrip())
    if proc.wait() != 0:
        clones.fail(v["id"], "The check stopped with an error:\n" + "\n".join(tail))


def delete_user_files(uid: int) -> None:
    """Everything a user uploaded or recorded, before the account row goes (rows go with it by cascade)."""
    for p in db.all_("select id from projects where owner_id=?", uid):
        delete_project(p["id"])
    for t in db.all_("select id from tasks where owner_id=?", uid):
        delete_task(t["id"])
    for v in db.all_("select id from voices where owner_id=?", uid):
        clones.delete(v["id"])


def delete_project(pid: int) -> None:
    """Files go; the row stays (marked deleted) so this month's minutes still count."""
    db.run("update projects set deleted_at=? where id=? and deleted_at is null", db.now(), pid)
    shutil.rmtree(folder(pid), ignore_errors=True)


def cleanup() -> None:
    """Delete projects older than their owner's plan keeps them (the promise on the Privacy page)."""
    for p in db.all_("select projects.id, projects.created_at, users.plan from projects join users on users.id=owner_id "
                     "where deleted_at is null"):
        busy = db.one("select 1 from jobs where project_id=? and status in ('waiting','running')", p["id"])
        if not busy and p["created_at"] < db.now() - db.PLANS[p["plan"]]["keep_days"] * 86400:
            delete_project(p["id"])
    for t in db.all_("select tasks.id, tasks.created_at, users.plan from tasks join users on users.id=owner_id "
                     "where deleted_at is null and status not in ('waiting','running')"):
        if t["created_at"] < db.now() - db.PLANS[t["plan"]]["keep_days"] * 86400:
            delete_task(t["id"])
    for v in db.all_("select id from voices where status in ('draft', 'failed') and created_at<?", db.now() - 86400):
        clones.delete(v["id"])  # sentences never recorded, or a check that failed: nothing kept for long


def loop(stop: threading.Event) -> None:
    db.run("update jobs set status='waiting' where status='running'")  # cut off by a restart: the CLI resumes it
    db.run("update tasks set status='waiting' where status='running'")
    db.run("update voices set status='waiting' where status='checking'")
    cleaned = 0.0
    while not stop.is_set():
        STATE["beat"] = time.time()
        if time.time() - cleaned > 3600:
            cleanup()
            cleaned = time.time()
        # ponytail: dubs before tool tasks on the one GPU; a fair queue if tasks start waiting too long
        job = db.one("update jobs set status='running', started_at=? where id=(select id from jobs where status='waiting' "
                     "order by id limit 1) returning *", db.now())
        task = None if job else db.one("update tasks set status='running', started_at=? where id=(select id from tasks "
                                       "where status='waiting' and deleted_at is null order by id limit 1) returning *", db.now())
        voice = None if job or task else db.one("update voices set status='checking' where id=(select id from voices "
                                                "where status='waiting' order by id limit 1) returning *")
        if not job and not task and not voice:
            stop.wait(2)
            continue
        STATE["job"] = f"dub #{job['id']}" if job else f"{task['kind']} #{task['id']}" if task else f"voice check #{voice['id']}"
        try:
            run_job(job) if job else run_task(task) if task else run_voice(voice)
        except Exception as e:  # e.g. the files were deleted meanwhile
            if voice:
                clones.fail(voice["id"], repr(e))
            else:
                table, row = ("jobs", job) if job else ("tasks", task)
                db.run(f"update {table} set status='failed', error=?, finished_at=? where id=?", repr(e), db.now(), row["id"])
        finally:
            STATE["job"] = STATE["proc"] = None


def stop_current() -> None:
    if STATE["proc"] and STATE["proc"].poll() is None:
        STATE["proc"].terminate()
