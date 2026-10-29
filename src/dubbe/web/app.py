"""DUBBE website: public pages, accounts, the dubbing app (upload, progress, review editor, export) and admin.

    dubbe-web        ->  http://127.0.0.1:8000   (the dub worker runs inside it, one job at a time)

Run it from the repository folder; settings are environment variables, see .env.example.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import yaml
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import ffmpeg, ratings, read_json, segment, tags, video_duration, write_json
from ..tts import sample_name
from ..report import STAGE, _t, ass, placed, subtitles, timeline_html, transcript
from . import auth, clones, db, tools, worker

HERE = Path(__file__).parent
_LANGS = yaml.safe_load((HERE.parent / "languages.yaml").read_text(encoding="utf8"))
LANGS = [k for k in _LANGS if k != "defaults"]
NAMES = {k: v.get("name", k) for k, v in _LANGS.items() if k != "defaults"}
PAIRS = {"korean-to-english": ("ko", "en"), "english-to-korean": ("en", "ko")}
VIDEO_TYPES = {".mp4", ".mov", ".m4v"}  # the pipeline reads the video stream's duration; WebM/MKV often lack it
MAX_UPLOAD = 2 * 1024 ** 3
TEAM_EMAIL = os.environ.get("DUBBE_TEAM_EMAIL", "")
TOPICS = ["Support", "Plans / business", "School / education", "Press", "Privacy or data request", "Report misuse", "Other"]
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# public examples: only clips we may publish. FLEURS is CC BY 4.0; the private test clips are never listed here.
EXAMPLES = {"fleurs-korean-to-english": {
    "title": "Read Korean sentences → English", "work": Path("work/fleurs_ko_kr.ko-en"),
    "credit": "Speech: Google FLEURS dataset, ko_kr dev split, CC BY 4.0 — 12 read sentences joined with pauses. "
              "Dubbed by DUBBE without any human correction.",
    "fix": ("Ghana", "Canaan")}}  # a real confident mistake in this dub (FLEURS reference: Canaan), see test-results.md
MSG = {  # ?m=... notices; fixed texts, so a link cannot put its own words on our page
    "verify-sent": "We sent you a link to confirm your email. (Local test install: the mail is in data/web/outbox/.)",
    "verified": "Email confirmed — you can start dubbing.", "signed-out": "You are signed out.",
    "bad-link": "This link is used or expired — ask for a new one.",
    "reset-sent": "If an account exists for that address, we sent a link to reset the password (valid 30 minutes).",
    "pw-changed": "Password changed. Please sign in again.", "sent": "Thanks — your message reached the team.",
    "waitlist": "You are on the waitlist; we will email you when paid plans open.", "deleted": "Project deleted.",
    "saved": "Saved.", "removed": "Deleted.", "voice": "Voice changed — press Re-dub to hear it.", "account-deleted": "Your account and files are deleted.",
    "voice-shared": "Sent for review: an admin listens to it before it is listed in the library.",
    "voice-unshared": "No longer shared. Nobody can start new speech or dubs with it.",
    "voice-deleted": "Voice deleted, with its recording.",
    "voice-added": "Added to your voices: pick it in Text to Speech or in a dub's review editor.",
    "voice-removed": "Removed from your voices.", "review-saved": "Thanks, your rating is saved.", "listing-saved": "Listing saved.",
    "speakers": "Speakers saved. Press Re-dub to hear the change.",
    "consent-needed": "Tick the consent box first: a speaker is only cloned with their permission.",
    "too-little-speech": "This speaker says too little to clone (8 seconds of speech are needed).",
    "speaker-cloned": "Speaker cloned from the video. The copy stays in this project only. Press Re-dub to hear it.",
    "speaker-renamed": "Name saved. The transcript and subtitles use it now."}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    stop = threading.Event()
    if os.environ.get("DUBBE_WORKER", "1") == "1":  # ponytail: worker thread in the web process; own process when the GPU is elsewhere
        threading.Thread(target=worker.loop, args=(stop,), daemon=True, name="dub-worker").start()
    yield
    stop.set()
    worker.stop_current()


app = FastAPI(title="DUBBE", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals.update(PLANS=db.PLANS, NAMES=NAMES, STAGE=STAGE, MSG=MSG, TAGS=tags, ERRORS=ratings.ERRORS,
                             STAGES=worker.STAGE_NAMES, t=_t, TOPICS=TOPICS)
templates.env.filters["date"] = lambda ts: datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.method == "POST":
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):  # cross-site form post
            return PlainTextResponse("Cross-site request refused.", 403)
        length = request.headers.get("content-length", "0")
        if request.url.path == "/app/new" and length.isdigit() and int(length) > MAX_UPLOAD + 10 ** 6:
            return PlainTextResponse("File too large (2 GB at most).", 413)  # refuse before receiving it
    r = await call_next(request)
    r.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin",
                      "X-Frame-Options": "SAMEORIGIN"})
    return r


@app.exception_handler(StarletteHTTPException)
async def not_found(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return page(request, "error.html", status=404)
    return await http_exception_handler(request, exc)  # keeps the 303 sign-in redirects


def used_minutes(uid: int) -> float:
    """Dubs and the speech-to-text / voice-isolator tools count their input length (text tools are free in the beta)."""
    month = datetime.datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    return sum(db.one(f"select coalesce(sum(minutes), 0) m from {t} where owner_id=? and created_at>=?", uid, month)["m"]
               for t in ("projects", "tasks"))


def minutes_left(u) -> float:
    return round(max(db.PLANS[u["plan"]]["minutes"] - used_minutes(u["id"]), 0), 1)


def page(request: Request, template: str, status: int = 200, **ctx):
    u = ctx.pop("user", None) or auth.current_user(request)
    extra = {"left": minutes_left(u)} if u else {}
    return templates.TemplateResponse(request, template, {"user": u, "admin": auth.is_admin(u), **extra, **ctx},
                                      status_code=status)


def go(url: str) -> RedirectResponse:
    return RedirectResponse(url, 303)


def ip_hash(request: Request) -> str:
    return hashlib.sha256((request.client.host if request.client else "").encode()).hexdigest()[:16]


# ---------------------------------------------------------------- public pages

def example(slug: str) -> dict | None:
    e = EXAMPLES.get(slug)
    if not e or not (e["work"] / "dubbed.mp4").exists():
        return None  # this install has not dubbed the example clip
    segs = read_json(e["work"] / "segments.json")["segments"]
    total = video_duration(e["work"] / "dubbed.mp4")
    wrong = next((s for s in segs if e.get("fix") and e["fix"][0] in (s["tgt_text"] or "")), None)
    return {**e, "slug": slug, "segs": segs, "minutes": round(total / 60, 1), "flagged": sum(bool(s.get("flag")) for s in segs),
            "short": min(segs, key=lambda s: len(s["tgt_text"] or "") or 999), "wrong": wrong,
            "timeline": timeline_html(segs, total, f"/examples/{slug}/dubbed")}


@app.get("/")
def home(request: Request):
    return page(request, "home.html", ex=example(next(iter(EXAMPLES))), voices=voices(),
                market_n=db.one("select count(*) n from voices where status='ready' and shared='listed'")["n"])


def voices(langs=("en", "ko")) -> list[dict]:
    """Preset voices with their measured pitch from languages.yaml; a sample plays when scripts/make_voice_samples.py has
    been run. English and Korean for the showcase pages; the voice pickers pass every language (each speaks with the same
    26 voices, so listing them all on the Voices page would repeat them 22 times)."""
    out = []
    for lang in langs:
        for v, info in _LANGS[lang]["tts"].get("voices", {}).items():
            vid = sample_name(v, lang, info)
            us_uk = {"a": "American", "b": "British"}.get(v[0], "")
            out.append({"id": vid, "key": v, "lang": lang, "f0": info["f0"], "register": info["register"],
                        "name": v.split("_")[1].title() if lang == "en" or info.get("prompt") else NAMES[lang],
                        "accent": us_uk if lang == "en" else f"{NAMES[lang]}, from the {us_uk} preset" if info.get("prompt")
                        else "MMS" if "mms" in v else "Chatterbox",
                        "sample": (db.ROOT / "samples" / f"{vid}.wav").exists(),
                        "default": v == _LANGS[lang]["tts"].get("voice")})
    return out


@app.get("/samples/{vid}")
def sample(vid: str):
    f = db.ROOT / "samples" / f"{vid}.wav"
    if vid not in {v["id"] for v in voices(LANGS)} or not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/wav")


def _static(name: str):
    def view(request: Request):
        return page(request, "legal.html" if name in ("terms", "use-policy", "privacy") else f"{name}.html", name=name,
                    voices=voices())
    return view


for _name in ["features", "education", "results", "about", "help", "safety", "terms", "use-policy", "privacy"]:
    app.add_api_route(f"/{_name}", _static(_name), methods=["GET"])


@app.get("/translate-video/{pair}")
def pair_page(request: Request, pair: str):
    if pair not in PAIRS:
        raise HTTPException(404)
    src, tgt = PAIRS[pair]
    return page(request, "pair.html", src=src, tgt=tgt, ex=example(next(iter(EXAMPLES))) if src == "ko" else None,
                voices=[v for v in voices() if v["lang"] == tgt])


@app.get("/examples")
def examples(request: Request):
    return page(request, "examples.html", examples=[e for e in map(example, EXAMPLES) if e])


def example_segment(slug: str, sid: int) -> tuple[dict, dict]:
    e = EXAMPLES.get(slug)
    if not e or not (e["work"] / "segments.json").exists():
        raise HTTPException(404)
    s = next((x for x in read_json(e["work"] / "segments.json")["segments"] if x["id"] == sid), None)
    if not s:
        raise HTTPException(404)
    return e, s


@app.get("/examples/{slug}/tts/{sid}")
def example_tts(slug: str, sid: int):
    e, s = example_segment(slug, sid)
    f = e["work"] / "tts" / f"{sid}.wav"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/wav")


@app.get("/examples/{slug}/orig/{sid}")
def example_original_audio(slug: str, sid: int):
    """The original speech of one sentence, for the original-vs-dub cards (cut once with ffmpeg, then cached)."""
    e, s = example_segment(slug, sid)
    f = db.ROOT / "cache" / slug / f"orig-{sid}.wav"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg("-ss", f"{s['start']:.2f}", "-to", f"{s['end'] + 0.25:.2f}", "-i", str(e["work"] / "original.wav"),
               "-ac", "1", "-ar", "24000", str(f))
    return FileResponse(f, media_type="audio/wav")


@app.get("/examples/{slug}/frame/{sid}")
def example_frame(slug: str, sid: int):
    """A still of the original video where the sentence is said (made once with ffmpeg, then cached)."""
    e, s = example_segment(slug, sid)
    f = db.ROOT / "cache" / slug / f"{sid}.jpg"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg("-ss", f"{s['start'] + 0.5:.2f}", "-i", read_json(e["work"] / "run.json")["video"],
               "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", str(f))
    return FileResponse(f, media_type="image/jpeg")


@app.get("/examples/{slug}/{kind}")
def example_file(slug: str, kind: str):
    e = EXAMPLES.get(slug)
    if not e or kind not in ("dubbed", "original") or not (e["work"] / "run.json").exists():
        raise HTTPException(404)
    f = e["work"] / "dubbed.mp4" if kind == "dubbed" else Path(read_json(e["work"] / "run.json")["video"])
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="video/mp4")


@app.get("/pricing")
def pricing(request: Request):
    return page(request, "pricing.html")


def too_many_messages(request: Request) -> bool:
    return db.one("select count(*) n from messages where ip=? and created_at>?", ip_hash(request), db.now() - 3600)["n"] >= 3


@app.post("/waitlist")
def waitlist(request: Request, email: str = Form(...), plan: str = Form(...)):
    if plan not in db.PLANS or not EMAIL.match(email.strip()):
        return page(request, "pricing.html", 400, error="Please enter a valid email.")
    if too_many_messages(request):
        return page(request, "pricing.html", 429, error="Too many messages from your network — try again in an hour.")
    db.run("insert into messages(email, topic, body, ip, created_at) values(?,?,?,?,?)",
           email.strip(), "Plan interest", f"Waitlist: {db.PLANS[plan]['name']}", ip_hash(request), db.now())
    return go("/pricing?m=waitlist")


@app.get("/contact")
def contact(request: Request, topic: str = ""):
    return page(request, "contact.html", form={"topic": {"report": "Report misuse", "school": "School / education"}.get(topic, "")})


@app.post("/contact")
def contact_send(request: Request, name: str = Form(""), email: str = Form(...), topic: str = Form(...),
                 body: str = Form(...), agree: str = Form(""), website: str = Form("")):
    form = {"name": name, "email": email, "topic": topic, "body": body}
    if website:  # hidden field only bots fill in: pretend it worked
        return go("/contact?m=sent")
    error = ("Please enter a valid email." if not EMAIL.match(email.strip()) else
             "Please choose a topic." if topic not in TOPICS else
             "Please write a message (2,000 characters at most)." if not body.strip() or len(body) > 2000 else
             "Please confirm you have read the Privacy notice." if not agree else
             "Too many messages from your network — try again in an hour." if too_many_messages(request) else None)
    if error:
        return page(request, "contact.html", 400, error=error, form=form)
    db.run("insert into messages(name, email, topic, body, ip, created_at) values(?,?,?,?,?,?)",
           name.strip()[:100], email.strip(), topic, body.strip(), ip_hash(request), db.now())
    if TEAM_EMAIL:
        auth.send_mail(TEAM_EMAIL, f"[DUBBE contact] {topic}", f"From: {name} <{email}>\n\n{body}")
    # fixed text, never their message: the form must not be usable to send others mail
    auth.send_mail(email.strip(), "We received your message", "Thanks for writing to the DUBBE team. "
                   "We answer within 2 working days.\n\n— DUBBE (student project, Inha University × HumbleBeeAI)")
    return go("/contact?m=sent")


# ---------------------------------------------------------------- accounts

def signed_in(request: Request, uid: int, to: str) -> RedirectResponse:
    r = go(to)
    r.set_cookie(auth.COOKIE, auth.start_session(uid), max_age=auth.SESSION_S, httponly=True, samesite="lax",
                 secure=request.url.scheme == "https")
    return r


def send_verify(u) -> None:
    t = auth.new_token(u["id"], "verify", 86400)
    auth.send_mail(u["email"], "Confirm your email for DUBBE",
                   f"Open this link to confirm your email (valid 24 hours):\n{auth.SITE_URL}/verify?token={t}\n\n"
                   "If you did not sign up, ignore this mail.")


@app.get("/signup")
def signup_form(request: Request):
    return page(request, "auth.html", mode="signup", form={})


@app.post("/signup")
def signup(request: Request, email: str = Form(...), password: str = Form(...), name: str = Form(""),
           agree: str = Form("")):
    email = email.strip().lower()
    error = ("Please enter a valid email." if not EMAIL.match(email) else
             "The password needs at least 10 characters." if len(password) < 10 else
             "Please accept the Terms and the Privacy notice." if not agree else
             "An account with this email exists — sign in, or reset the password." if
             db.one("select 1 from users where email=?", email) else None)
    if error:
        return page(request, "auth.html", 400, mode="signup", error=error, form={"email": email, "name": name})
    uid = db.run("insert into users(email, name, pw, created_at) values(?,?,?,?)",
                 email, name.strip()[:100], auth.hash_pw(password), db.now())
    send_verify(db.one("select * from users where id=?", uid))
    return signed_in(request, uid, "/app?m=verify-sent")


@app.get("/verify")
def verify(token: str = ""):
    uid = auth.use_token(token, "verify")
    if uid is None:
        return go("/app?m=bad-link")
    db.run("update users set verified_at=? where id=?", db.now(), uid)
    return go("/app?m=verified")


@app.post("/resend")
def resend(request: Request):
    send_verify(auth.require_user(request))
    return go("/app?m=verify-sent")


@app.get("/signin")
def signin_form(request: Request, next: str = "/app"):
    return page(request, "auth.html", mode="signin", form={}, next=next)


@app.post("/signin")
def signin(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("/app")):
    email = email.strip().lower()
    next = next if next.startswith("/") and not next.startswith("//") else "/app"  # only our own pages
    if auth.throttled(email):
        return page(request, "auth.html", 429, mode="signin", error="Too many tries. Wait 15 minutes, or reset the password.",
                    form={"email": email}, next=next)
    u = db.one("select * from users where email=?", email)
    if not u or not auth.check_pw(password, u["pw"]):
        auth.failed(email)
        return page(request, "auth.html", 400, mode="signin", error="Email or password is wrong.", form={"email": email}, next=next)
    return signed_in(request, u["id"], next)


@app.post("/signout")
def signout(request: Request):
    auth.end_session(request.cookies.get(auth.COOKIE, ""))
    r = go("/?m=signed-out")
    r.delete_cookie(auth.COOKIE)
    return r


@app.get("/forgot")
def forgot_form(request: Request):
    return page(request, "auth.html", mode="forgot")


@app.post("/forgot")
def forgot(request: Request, email: str = Form(...)):
    u = db.one("select * from users where email=?", email.strip().lower())
    if u:
        t = auth.new_token(u["id"], "reset", 1800)
        auth.send_mail(u["email"], "Reset your DUBBE password",
                       f"Open this link to choose a new password (valid 30 minutes, works once):\n"
                       f"{auth.SITE_URL}/reset?token={t}\n\nIf you did not ask for this, ignore this mail.")
    return go("/forgot?m=reset-sent")  # same answer either way: does not reveal who has an account


@app.get("/reset")
def reset_form(request: Request, token: str = ""):
    return page(request, "auth.html", mode="reset", token=token)


@app.post("/reset")
def reset(request: Request, token: str = Form(...), password: str = Form(...)):
    if len(password) < 10:
        return page(request, "auth.html", 400, mode="reset", token=token, error="The password needs at least 10 characters.")
    uid = auth.use_token(token, "reset")
    if uid is None:
        return page(request, "auth.html", 400, mode="reset", token="", error="This link is used or expired — ask for a new one.")
    db.run("update users set pw=? where id=?", auth.hash_pw(password), uid)
    auth.end_all_sessions(uid)
    return go("/signin?m=pw-changed")


# ---------------------------------------------------------------- app

def own_project(request: Request, pid: int):
    u = auth.require_user(request)
    p = db.one("select * from projects where id=? and deleted_at is null", pid)
    if not p or (p["owner_id"] != u["id"] and not auth.is_admin(u)):
        raise HTTPException(404)  # not "forbidden": does not reveal that the project exists
    return u, p


def last_job(pid: int):
    return db.one("select * from jobs where project_id=? order by id desc limit 1", pid)


def flagged(p) -> int | None:
    f = worker.work(p) / "segments.json"
    return sum(bool(s.get("flag")) for s in read_json(f)["segments"]) if f.exists() else None


def n_speakers(p) -> int:
    f = worker.work(p) / "segments.json"
    return len(read_json(f).get("speakers") or {}) if f.exists() else 0


def task_rows(uid: int, limit: int = 200, kind: str = "") -> list[dict]:
    rows = db.all_("select * from tasks where owner_id=? and deleted_at is null" + (" and kind=?" if kind else "") +
                   " order by id desc limit ?", uid, *([kind] if kind else []), limit)
    return [{"t": t, "r": json.loads(t["result"]) if t["result"] else None} for t in rows]


@app.get("/app")
def app_home(request: Request):
    u = auth.require_user(request)
    rows = db.all_("select * from projects where owner_id=? and deleted_at is null order by id desc", u["id"])
    recent = [{"p": p, "job": last_job(p["id"]), "flagged": flagged(p), "speakers": n_speakers(p)} for p in rows[:4]]
    return page(request, "app_home.html", user=u, recent=recent, tasks=task_rows(u["id"], 6), trending=clones.market(u)[:4],
                cloning=clones.enabled(),
                used=round(used_minutes(u["id"]), 1), n_projects=len(rows),
                n_tasks=db.one("select count(*) n from tasks where owner_id=? and deleted_at is null", u["id"])["n"],
                to_check=sum(x["flagged"] or 0 for x in recent))


@app.get("/app/projects")
def projects_page(request: Request):
    u = auth.require_user(request)
    rows = db.all_("select * from projects where owner_id=? and deleted_at is null order by id desc", u["id"])
    projects = [{"p": p, "job": last_job(p["id"]), "flagged": flagged(p), "speakers": n_speakers(p)} for p in rows]
    return page(request, "dashboard.html", user=u, projects=projects, used=round(used_minutes(u["id"]), 1))


def save_upload(file: UploadFile, dest: Path) -> bool:
    """Stream an upload to disk; False (and nothing left behind) when it is bigger than MAX_UPLOAD."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with dest.open("wb") as out:
        while chunk := file.file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                break
            out.write(chunk)
    if size > MAX_UPLOAD:
        dest.unlink()
    return size <= MAX_UPLOAD


def media_minutes(path: Path) -> float:
    """Length of an audio or video file in minutes; raises if ffprobe cannot read it."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip()) / 60


def limit_error(u, minutes: float) -> str | None:
    plan = db.PLANS[u["plan"]]
    if auth.is_admin(u):  # the team tests without limits
        return None
    if minutes > plan["max_len"]:
        return f"This file is {minutes:.1f} min; your plan takes files up to {plan['max_len']} min."
    if minutes > minutes_left(u):
        return f"This file is {minutes:.1f} min, but you have {minutes_left(u)} min left this month."
    return None


@app.get("/app/new")
def new_form(request: Request):
    u = auth.require_user(request)
    return page(request, "new.html", user=u, langs=LANGS, form={"src": "ko", "tgt": "en", "voice": request.query_params.get("voice", "")},
                voices=voices(LANGS), clones=clones.usable(u) if clones.enabled() else [])


@app.post("/app/new")
def new_dub(request: Request, file: UploadFile = File(...), src: str = Form(...), tgt: str = Form(...),
            keep_bg: str = Form(""), slow: float = Form(1.0), rights: str = Form(""), voice: str = Form("")):
    u = auth.require_user(request)
    form = {"src": src, "tgt": tgt, "voice": voice}
    mine = clones.usable(u) if clones.enabled() else []

    def fail(msg: str, pid: int | None = None):
        if pid:
            shutil.rmtree(worker.folder(pid), ignore_errors=True)
            db.run("delete from projects where id=?", pid)
        return page(request, "new.html", 400, user=u, langs=LANGS, form=form, error=msg, voices=voices(LANGS), clones=mine)

    ext = Path(file.filename or "").suffix.lower()
    if not u["verified_at"]:
        return fail("Please confirm your email first (see the link we sent you).")
    if src not in LANGS or tgt not in LANGS or src == tgt:
        return fail("Choose two different languages.")
    if voice and voice not in _LANGS[tgt]["tts"].get("voices", {}) and voice not in {f"clone:{c['id']}" for c in mine}:
        return fail("Choose a voice from the list.")
    if not rights:
        return fail("Please confirm you own this video or have a licence that allows changing it.")
    if ext not in VIDEO_TYPES:
        return fail("Upload an MP4 or MOV video.")
    pid = db.run("insert into projects(owner_id, title, src, tgt, keep_bg, slow, minutes, created_at, voice) "
                 "values(?,?,?,?,?,?,0,?,?)", u["id"], Path(file.filename).stem[:80] or "Video", src, tgt,
                 int(bool(keep_bg)), min(max(slow, 1.0), 1.3), db.now(), voice)
    if not save_upload(file, worker.folder(pid) / f"video{ext}"):
        return fail("File too large (2 GB at most).", pid)
    try:
        minutes = video_duration(worker.folder(pid) / f"video{ext}") / 60
    except Exception:
        return fail("This file could not be read as a video.", pid)
    if error := limit_error(u, minutes):
        return fail(error, pid)
    db.run("update projects set minutes=? where id=?", round(minutes, 2), pid)
    jid = db.run("insert into jobs(project_id, created_at) values(?,?)", pid, db.now())
    return go(f"/app/jobs/{jid}")


@app.get("/app/jobs/{jid}")
def job_page(request: Request, jid: int):
    job = db.one("select * from jobs where id=?", jid)
    if not job:
        raise HTTPException(404)
    u, p = own_project(request, job["project_id"])
    stages = worker.STAGE_NAMES[worker.STAGE_NAMES.index(job["from_stage"]) if job["from_stage"] else 0:]
    ahead = db.one("select count(*) n from jobs where status='waiting' and id<?", jid)["n"]
    return page(request, "job.html", user=u, p=p, job=job, stages=stages, ahead=ahead)


def queue(pid: int, from_stage: str | None) -> int:
    busy = db.one("select id from jobs where project_id=? and status in ('waiting','running')", pid)
    return busy["id"] if busy else db.run("insert into jobs(project_id, from_stage, created_at) values(?,?,?)",
                                          pid, from_stage, db.now())


@app.post("/app/jobs/{jid}/retry")
def retry(request: Request, jid: int):
    job = db.one("select * from jobs where id=? and status='failed'", jid)
    if not job:
        raise HTTPException(404)
    own_project(request, job["project_id"])
    return go(f"/app/jobs/{queue(job['project_id'], job['stage'] or job['from_stage'])}")


def segments(p) -> dict:
    f = worker.work(p) / "segments.json"
    if not f.exists():
        raise HTTPException(404)
    return read_json(f)


@app.get("/app/p/{pid}")
def editor(request: Request, pid: int, blind: int = 0, only: str = "", s: int = 0):
    u, p = own_project(request, pid)
    job = last_job(pid)
    if not (worker.work(p) / "dubbed.mp4").exists():
        return go(f"/app/jobs/{job['id']}") if job else go("/app")
    data = segments(p)
    segs = data["segments"]
    shown = [x for x in segs if x.get("flag")] if only == "flagged" else segs
    mine = {r["id"]: r for r in ratings.load(worker.work(p)) if r["rater"] == u["email"]}
    speakers = data.get("speakers") or {"S1": {"name": "Speaker 1"}}
    counts = {sp: sum(x.get("speaker", "S1") == sp for x in segs) for sp in speakers}
    timeline = timeline_html(segs, video_duration(worker.work(p) / "dubbed.mp4"), f"/app/p/{pid}/file/dubbed.mp4",
                             show_flags=not blind)
    return page(request, "editor.html", user=u, p=p, job=job, segs=shown, total_segs=len(segs), timeline=timeline,
                blind=blind, only=only, sel=s, mine=mine, data=data, placed=placed, speakers=speakers, counts=counts,
                voice_opts={sp: voice_options(p, sp) for sp in speakers}, cloning=clones.enabled(),
                summary=ratings.summarize(ratings.load(worker.work(p)), segs))


def saved(request: Request, pid: int, sid: int):
    """Forms on the editor are sent by fetch (the video keeps playing); without JavaScript, back to the sentence."""
    return Response(status_code=204) if request.headers.get("x-fetch") else go(f"/app/p/{pid}?s={sid}#s{sid}")


@app.post("/app/p/{pid}/s/{sid}")
def save_sentence(request: Request, pid: int, sid: int, text: str = Form(""),
                  chosen: list[str] = Form([], alias="tags"), speaker: str = Form("")):
    u, p = own_project(request, pid)
    data = segments(p)
    s = next((x for x in data["segments"] if x["id"] == sid), None)
    if not s:
        raise HTTPException(404)
    segment.edit(s, text[:1000], chosen)
    spk = data.setdefault("speakers", {"S1": {"name": "Speaker 1"}})
    if speaker == "new":  # two similar voices detected as one person (test-results C21): split one out
        n = max(int(k[1:]) for k in spk) + 1
        free = [v for v in _LANGS[p["tgt"]]["tts"].get("voices", {}) if v not in {x.get("voice") for x in spk.values()}]
        spk[speaker := f"S{n}"] = {"name": f"Speaker {n}", **({"voice": free[0], "override": True} if free else {})}
    if speaker in spk and speaker != s.get("speaker", "S1"):  # the detection got it wrong
        s["speaker"], data["speakers_edited"] = speaker, True
    write_json(worker.work(p) / "segments.json", data)
    return saved(request, pid, sid)


@app.post("/app/p/{pid}/s/{sid}/rate")
def rate(request: Request, pid: int, sid: int, score: int = Form(...), errors: list[str] = Form([]),
         comment: str = Form(""), blind: int = Form(0)):
    u, p = own_project(request, pid)
    if sid not in {x["id"] for x in segments(p)["segments"]}:
        raise HTTPException(404)
    ratings.save(worker.work(p), u["email"], sid, min(max(score, 0), 100), [e for e in errors if e in ratings.ERRORS],
                 comment[:500], bool(blind))
    return saved(request, pid, sid)


def voice_options(p, sp: str = "S1") -> list[tuple[str, str]]:
    """For one speaker of a project: their own voice cloned from the video (if the uploader consented), the preset
    voices of the target language, and the clones the owner may use (own, and the ones they got)."""
    owner = db.one("select * from users where id=?", p["owner_id"])
    own = [(f"video:{sp}", "Their own voice (cloned from the video, with consent)")] if clones.speaker_file(p["id"], sp).exists() else []
    presets = [(v, v) for v in _LANGS[p["tgt"]]["tts"].get("voices", {})]
    return own + presets + [(f"clone:{c['id']}", f"{c['name']} — " + ("your voice" if c["owner_id"] == owner["id"] else
                            f"by {c['owner_name'] or 'a user'}")) for c in (clones.usable(owner) if clones.enabled() else [])]


def start_over(request: Request, pid: int, stage: str):
    """Re-run from `stage` with speaker detection included: the reviewer's speaker changes and the voices cloned from
    the video start over (after this, S2 may be someone else); edited translations and tags carry over."""
    u, p = own_project(request, pid)
    data = segments(p)
    data.pop("speakers_edited", None)
    write_json(worker.work(p) / "segments.json", data)
    shutil.rmtree(clones.speaker_file(pid, "S1").parent, ignore_errors=True)
    return go(f"/app/jobs/{queue(pid, stage)}")


@app.post("/app/p/{pid}/detect-speakers")
def detect_speakers(request: Request, pid: int):
    """Find the speakers again: projects dubbed before detection existed, or a detection the reviewer wants redone."""
    return start_over(request, pid, "speakers")


@app.post("/app/p/{pid}/rerun")
def rerun(request: Request, pid: int):
    """Transcribe and translate again with the current models, for projects made before an upgrade (test-results C23)."""
    return start_over(request, pid, "asr")


@app.post("/app/p/{pid}/speakers/{sp}")
def set_speaker(request: Request, pid: int, sp: str, name: str = Form(""), voice: str = Form(""), merge: str = Form("")):
    """Rename a speaker, give them a voice, or merge them into another one (the detection split one person in two)."""
    u, p = own_project(request, pid)
    data = segments(p)
    spk = data.setdefault("speakers", {})
    if sp not in spk:
        raise HTTPException(404)
    if merge:
        if merge not in spk or merge == sp:
            raise HTTPException(400)
        for s in data["segments"]:
            if s.get("speaker", "S1") == sp:
                s["speaker"] = merge
        del spk[sp]
    else:
        if voice and voice not in dict(voice_options(p, sp)):
            raise HTTPException(400)
        spk[sp].update(name=name.strip()[:40] or spk[sp].get("name") or sp, **({"voice": voice, "override": True} if voice else {}))
    data["speakers_edited"] = True  # a re-run never redoes the detection over the reviewer's corrections
    write_json(worker.work(p) / "segments.json", data)
    return go(f"/app/p/{pid}?m=speakers#speakers")


@app.post("/app/p/{pid}/speakers/{sp}/clone")
def clone_speaker(request: Request, pid: int, sp: str, consent: str = Form("")):
    """Their own voice for a speaker of this video - only with consent, kept only in this project (clones.py)."""
    u, p = own_project(request, pid)
    data = segments(p)
    if sp not in (data.get("speakers") or {}) or not clones.enabled():
        raise HTTPException(404)
    if not consent:
        return go(f"/app/p/{pid}?m=consent-needed#speakers")
    secs = clones.make_speaker_clone(pid, worker.work(p), data["segments"], sp)
    if secs < clones.MIN_SECONDS:
        return go(f"/app/p/{pid}?m=too-little-speech#speakers")
    data["speakers"][sp].update(voice=f"video:{sp}", override=True,
                                clone_consent={"by": u["email"], "at": db.now(), "seconds": round(secs, 1)})
    data["speakers_edited"] = True
    write_json(worker.work(p) / "segments.json", data)
    return go(f"/app/p/{pid}?m=speaker-cloned#speakers")


@app.post("/app/p/{pid}/redub")
def redub(request: Request, pid: int):
    own_project(request, pid)
    return go(f"/app/jobs/{queue(pid, 'tts')}")  # new text, tags and voice take effect from speech synthesis on


# files the report and the editor link to; nothing else in the project folder is served
SERVED = re.compile(r"^(dubbed\.mp4|report\.html|tts/\d+\.wav)$")


@app.get("/app/p/{pid}/file/{name:path}")
def project_file(request: Request, pid: int, name: str):
    u, p = own_project(request, pid)
    f = worker.video(pid) if name == "original" else worker.work(p) / name if SERVED.match(name) else None
    if not f or not f.exists():
        raise HTTPException(404)
    return FileResponse(f)


@app.get("/app/p/{pid}/export")
def export(request: Request, pid: int):
    u, p = own_project(request, pid)
    if not (worker.work(p) / "dubbed.mp4").exists():
        raise HTTPException(404)
    return page(request, "export.html", user=u, p=p)


@app.get("/app/p/{pid}/download/{kind}")
def download(request: Request, pid: int, kind: str):
    u, p = own_project(request, pid)
    w = worker.work(p)
    base = re.sub(r"[^A-Za-z0-9-]+", "_", p["title"]).strip("_") or "video"  # ASCII: goes into a header
    if kind == "video":
        return FileResponse(w / "dubbed.mp4", filename=f"{base}.{p['tgt']}.AI-dubbed.mp4")
    if kind == "report":
        return FileResponse(w / "report.html", filename=f"{base}.report.html")
    m = re.fullmatch(r"(src|tgt)(\.color)?\.(srt|vtt|txt|ass)", kind)
    if not m:
        raise HTTPException(404)
    data = segments(p)
    segs, field, spk = data["segments"], f"{m[1]}_text", data.get("speakers") or {}
    text = {"txt": lambda: transcript(segs, field, spk), "ass": lambda: ass(segs, field, spk, p[m[1]]),
            "srt": lambda: subtitles(segs, field, speakers=spk if m[2] else None),
            "vtt": lambda: subtitles(segs, field, True, speakers=spk if m[2] else None)}[m[3]]()
    return Response(text, media_type={"vtt": "text/vtt", "srt": "application/x-subrip", "txt": "text/plain; charset=utf-8",
                                      "ass": "text/x-ssa"}[m[3]],
                    headers={"Content-Disposition": f'attachment; filename="{base}.{p[m[1]]}{m[2] or ""}.{m[3]}"'})


@app.post("/app/p/{pid}/delete")
def delete(request: Request, pid: int):
    own_project(request, pid)
    if db.one("select 1 from jobs where project_id=? and status in ('waiting','running')", pid):
        return go(f"/app/jobs/{last_job(pid)['id']}")  # wait for the running job first
    worker.delete_project(pid)
    return go("/app?m=deleted")


@app.get("/app/plan")
def plan_page(request: Request):
    u = auth.require_user(request)
    rows = db.all_("select * from projects where owner_id=? and deleted_at is null order by id desc", u["id"])
    keep = db.PLANS[u["plan"]]["keep_days"] * 86400
    return page(request, "plan.html", user=u, used=round(used_minutes(u["id"]), 1),
                projects=[{"p": p, "expires": p["created_at"] + keep} for p in rows])


@app.get("/app/settings")
def settings_form(request: Request):
    return page(request, "settings.html", user=auth.require_user(request))


@app.post("/app/settings")
def settings(request: Request, action: str = Form(...), name: str = Form(""), current: str = Form(""),
             new: str = Form("")):
    u = auth.require_user(request)
    if action == "name":
        db.run("update users set name=? where id=?", name.strip()[:100], u["id"])
        return go("/app/settings?m=saved")
    if not auth.check_pw(current, u["pw"]):
        return page(request, "settings.html", 400, user=u, error="The current password is wrong.")
    if action == "password":
        if len(new) < 10:
            return page(request, "settings.html", 400, user=u, error="The new password needs at least 10 characters.")
        db.run("update users set pw=? where id=?", auth.hash_pw(new), u["id"])
        auth.end_all_sessions(u["id"])
        return go("/signin?m=pw-changed")
    if action == "delete":
        worker.delete_user_files(u["id"])  # videos, tool files, voice recordings
        db.run("delete from users where id=?", u["id"])  # sessions, tokens, projects, jobs, voices go with it
        r = go("/?m=account-deleted")
        r.delete_cookie(auth.COOKIE)
        return r
    raise HTTPException(400)


# ---------------------------------------------------------------- tools: text to speech, speech to text, translate, voice isolator

TOOLS = {"tts": "Text to Speech", "stt": "Speech to Text", "speakers": "Speaker Detection", "captions": "Subtitles",
         "translate": "Translate", "isolate": "Voice Isolator"}
SPK_COLORS = ["#f76b15", "#6e56cf", "#30a46c", "#3b82f6", "#e5484d", "#e2a336", "#12a594", "#d6409f"]
MEDIA_TYPES = VIDEO_TYPES | {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
MAX_CHARS = {"tts": 2000, "translate": 5000}
templates.env.globals.update(TOOLS=TOOLS, MAX_CHARS=MAX_CHARS, SPK_COLORS=SPK_COLORS)


def new_task(u, kind: str, title: str, params: dict, status: str = "waiting") -> int:
    return db.run("insert into tasks(owner_id, kind, title, params, status, created_at) values(?,?,?,?,?,?)",
                  u["id"], kind, title.strip()[:80] or TOOLS[kind], json.dumps(params, ensure_ascii=False), status, db.now())


def own_task(request: Request, tid: int):
    u = auth.require_user(request)
    t = db.one("select * from tasks where id=? and deleted_at is null", tid)
    if not t or (t["owner_id"] != u["id"] and not auth.is_admin(u)):
        raise HTTPException(404)
    return u, t


def tool_page(request: Request, u, kind: str, status: int = 200, **ctx):
    return page(request, f"tool_{kind}.html", status, user=u, langs=LANGS, voices=voices(LANGS), recent=task_rows(u["id"], 5, kind),
                clones=clones.usable(u) if clones.enabled() else [], **{"form": {}, **ctx})


def _tool_form(kind: str):
    def view(request: Request):  # ?voice=...&lang=... (from the voice library) pre-fills the form
        return tool_page(request, auth.require_user(request), kind, form=dict(request.query_params))
    return view


for _kind in TOOLS:
    app.add_api_route(f"/app/{_kind}", _tool_form(_kind), methods=["GET"])


@app.post("/app/tts")
def tts_create(request: Request, text: str = Form(""), lang: str = Form("en"), voice: str = Form("")):
    u = auth.require_user(request)
    keys = {v["id"]: v["key"] for v in voices(LANGS) if v["lang"] == lang}
    keys |= {f"clone:{c['id']}": f"clone:{c['id']}" for c in (clones.usable(u) if clones.enabled() else [])}  # any language
    error = ("Please confirm your email first." if not u["verified_at"] else
             "Write some text." if not text.strip() else
             f"At most {MAX_CHARS['tts']:,} characters." if len(text) > MAX_CHARS["tts"] else
             "Choose a voice for this language." if voice not in keys else None)
    if error:
        return tool_page(request, u, "tts", 400, error=error, form={"text": text, "voice": voice, "lang": lang})
    return go(f"/app/tasks/{new_task(u, 'tts', text, {'text': text.strip(), 'lang': lang, 'voice': keys[voice]})}")


@app.post("/app/translate")
def translate_create(request: Request, text: str = Form(""), src: str = Form("ko"), tgt: str = Form("en")):
    u = auth.require_user(request)
    error = ("Please confirm your email first." if not u["verified_at"] else
             "Write some text." if not text.strip() else
             f"At most {MAX_CHARS['translate']:,} characters." if len(text) > MAX_CHARS["translate"] else
             "Choose two different languages." if src not in LANGS or tgt not in LANGS or src == tgt else None)
    if error:
        return tool_page(request, u, "translate", 400, error=error, form={"text": text, "src": src, "tgt": tgt})
    return go(f"/app/tasks/{new_task(u, 'translate', text, {'text': text.strip(), 'src': src, 'tgt': tgt})}")


def media_task(request: Request, u, kind: str, file: UploadFile, params: dict, rights: str, form: dict):
    """Speech to text and voice isolator: upload, check type, length and plan, then queue."""
    ext = Path(file.filename or "").suffix.lower()
    error = ("Please confirm your email first." if not u["verified_at"] else
             "Please confirm you own this file or may use it." if not rights else
             "Upload an MP4, MOV, MP3, WAV, M4A, OGG or FLAC file." if ext not in MEDIA_TYPES else None)
    if error:
        return tool_page(request, u, kind, 400, error=error, form=form)
    tid = new_task(u, kind, Path(file.filename).stem, params, status="uploading")  # the worker skips it until checked
    dest = tools.folder(tid) / f"input{ext}"
    try:
        error = None if save_upload(file, dest) else "File too large (2 GB at most)."
        minutes = 0.0 if error else media_minutes(dest)
    except Exception:
        error = "This file could not be read as audio or video."
    error = error or limit_error(u, minutes)
    if error:
        shutil.rmtree(tools.folder(tid), ignore_errors=True)
        db.run("delete from tasks where id=?", tid)
        return tool_page(request, u, kind, 400, error=error, form=form)
    db.run("update tasks set minutes=?, status='waiting' where id=?", round(minutes, 2), tid)
    return go(f"/app/tasks/{tid}")


@app.post("/app/stt")
def stt_create(request: Request, file: UploadFile = File(...), src: str = Form("ko"), to: str = Form(""),
               rights: str = Form(""), speakers: str = Form("")):
    u = auth.require_user(request)
    src = src if src in LANGS else "ko"
    return media_task(request, u, "stt", file, {"src": src, "to": to if to in LANGS and to != src else "", "speakers": bool(speakers)},
                      rights, {"src": src, "to": to, "speakers": speakers})


@app.post("/app/speakers")
def speakers_create(request: Request, file: UploadFile = File(...), src: str = Form("ko"), rights: str = Form("")):
    u = auth.require_user(request)
    src = src if src in LANGS else "ko"
    return media_task(request, u, "speakers", file, {"src": src}, rights, {"src": src})


def own_speaker(request: Request, tid: int, sp: str):
    u, t = own_task(request, tid)
    f = tools.folder(tid) / "segments.json"
    data = read_json(f) if t["kind"] in ("speakers", "captions") and t["status"] == "done" and f.exists() else {}
    if sp not in (data.get("speakers") or {}):
        raise HTTPException(404)
    return u, t, data


@app.post("/app/tasks/{tid}/speakers/{sp}")
def task_speaker_name(request: Request, tid: int, sp: str, name: str = Form("")):
    """Name a speaker: the transcript and subtitles are written again with the name."""
    u, t, data = own_speaker(request, tid, sp)
    data["speakers"][sp]["name"] = name.strip()[:40] or data["speakers"][sp]["name"]
    write_json(tools.folder(tid) / "segments.json", data)
    out = tools.folder(tid)
    result = tools.speaker_files(out) if t["kind"] == "speakers" else tools.caption_files(out, json.loads(t["params"]), tid)
    db.run("update tasks set result=? where id=?", json.dumps(result, ensure_ascii=False), tid)
    return go(f"/app/tasks/{tid}?m=speaker-renamed#{sp}")


@app.post("/app/captions")
def captions_create(request: Request, file: UploadFile = File(...), src: str = Form("ko"), to: str = Form(""),
                    rights: str = Form("")):
    u = auth.require_user(request)
    src = src if src in LANGS else "ko"
    return media_task(request, u, "captions", file, {"src": src, "to": to if to in LANGS and to != src else ""}, rights,
                      {"src": src, "to": to})


@app.post("/app/tasks/{tid}/burn")
def captions_burn(request: Request, tid: int, lang: str = Form("")):
    """Burn one language's captions into the video: the task runs once more, only that step."""
    u, t = own_task(request, tid)
    p, r = json.loads(t["params"]), json.loads(t["result"] or "{}")
    if t["kind"] != "captions" or t["status"] != "done" or lang not in r.get("langs", []) or not (r.get("video") or p.get("project")):
        raise HTTPException(404)
    db.run("update tasks set params=?, status='waiting' where id=?", json.dumps({**p, "burn": lang}, ensure_ascii=False), tid)
    return go(f"/app/tasks/{tid}")


@app.post("/app/p/{pid}/captions")
def dub_captions(request: Request, pid: int, lang: str = Form("tgt")):
    """The dubbed video with captions burned in (a Subtitles task on the dub's own sentences, timed to the dub)."""
    u, p = own_project(request, pid)
    job = last_job(pid)
    if lang not in ("src", "tgt") or not job or job["status"] != "done":
        raise HTTPException(404)
    tid = new_task(u, "captions", p["title"], {"project": pid, "src": p["src"], "to": p["tgt"], "burn": p[lang]})
    return go(f"/app/tasks/{tid}")


@app.post("/app/tasks/{tid}/speakers/{sp}/clone")
def task_speaker_clone(request: Request, tid: int, sp: str, name: str = Form(""), consent: str = Form("")):
    """A speaker of the uploaded video as a voice in the uploader's library, only with consent. It goes through the
    same check as a recorded clone and stays private: a voice from a video can never be published."""
    u, t, data = own_speaker(request, tid, sp)
    if not clones.enabled() or t["owner_id"] != u["id"]:
        raise HTTPException(404)
    if not consent:
        return go(f"/app/tasks/{tid}?m=consent-needed#{sp}")
    wav, seconds, said = clones.speaker_clip(tools.folder(tid), data["segments"], sp)
    if not wav:
        return go(f"/app/tasks/{tid}?m=too-little-speech#{sp}")
    vid = db.run("insert into voices(owner_id, name, lang, script, source, created_at) values(?,?,?,?,?,?)", u["id"],
                 (name.strip() or data["speakers"][sp]["name"])[:60], json.loads(t["params"])["src"], said, f"video:{tid}", db.now())
    clones.save(vid, "recording", wav)
    db.run("update voices set status='waiting' where id=?", vid)  # the worker checks it like a recorded clone
    return go(f"/app/studio/{vid}")


@app.post("/app/isolate")
def isolate_create(request: Request, file: UploadFile = File(...), rights: str = Form("")):
    u = auth.require_user(request)
    return media_task(request, u, "isolate", file, {}, rights, {})


@app.get("/app/tasks/{tid}")
def task_page(request: Request, tid: int):
    u, t = own_task(request, tid)
    ahead = db.one("select count(*) n from tasks where status='waiting' and id<?", tid)["n"] + \
        db.one("select count(*) n from jobs where status in ('waiting','running')")["n"]
    return page(request, "task.html", user=u, t=t, p=json.loads(t["params"]), ahead=ahead,
                result=json.loads(t["result"]) if t["result"] else None, cloning=clones.enabled())


@app.get("/app/tasks/{tid}/file/{name}")
def task_file(request: Request, tid: int, name: str, dl: int = 0):
    u, t = own_task(request, tid)
    if name not in (json.loads(t["result"]) if t["result"] else {}).get("files", []):
        raise HTTPException(404)  # only the files the tool listed
    return FileResponse(tools.folder(tid) / name, filename=f"dubbe-{t['kind']}-{tid}-{name}" if dl else None,
                        media_type="text/vtt" if name.endswith(".vtt") else None)  # a <track> needs text/vtt


@app.post("/app/tasks/{tid}/delete")
def task_delete(request: Request, tid: int):
    u, t = own_task(request, tid)
    if t["status"] in ("waiting", "running", "uploading"):
        return go(f"/app/tasks/{tid}")
    worker.delete_task(tid)
    return go("/app/history?m=removed")


@app.get("/app/history")
def history(request: Request, kind: str = ""):
    u = auth.require_user(request)
    return page(request, "history.html", user=u, items=task_rows(u["id"], 200, kind if kind in TOOLS else ""), kind=kind)


# ---------------------------------------------------------------- voices: presets, your own clones, the shared library (clones.py)

def own_voice(request: Request, vid: int):
    u = auth.require_user(request)
    v = db.one("select * from voices where id=?", vid)
    if not v or (v["owner_id"] != u["id"] and not auth.is_admin(u)):
        raise HTTPException(404)
    return u, v


@app.get("/app/voices")
def voice_library(request: Request, lang: str = "en"):
    """The user's clones, the voices they got, and the presets — every preset in the language picked (?lang=)."""
    u = auth.require_user(request)
    lang = lang if lang in LANGS else "en"
    mine = db.all_("select * from voices where owner_id=? and status<>'draft' order by id desc", u["id"])
    return page(request, "voices.html", user=u, voices=voices((lang,)), lang=lang, langs=LANGS,
                mine=[{"v": v, "s": clones.stats(v)} for v in mine],
                added=[v for v in clones.usable(u) if v["owner_id"] != u["id"]], cloning=clones.enabled())


@app.get("/app/voices/new")
def voice_new(request: Request, lang: str = "en"):
    """The consent recording: three sentences picked now, valid for 30 minutes, read aloud in the browser."""
    u = auth.require_user(request)
    if not clones.enabled():
        raise HTTPException(404)
    if not u["verified_at"]:
        return page(request, "voice_new.html", user=u, v=None, langs=LANGS, error="Please confirm your email first.")
    lang = lang if lang in clones.SENTENCES else "en"  # the consent sentences exist in English and Korean
    vid = db.run("insert into voices(owner_id, lang, script, created_at) values(?,?,?,?)", u["id"], lang, clones.script(lang), db.now())
    return page(request, "voice_new.html", user=u, v=db.one("select * from voices where id=?", vid), langs=LANGS)


@app.post("/app/voices/{vid}/record")
def voice_record(request: Request, vid: int, file: UploadFile = File(...), name: str = Form(""), own: str = Form(""),
                 consent: str = Form("")):
    """Answers in plain text: the page sends the recording with fetch and shows the message."""
    u, v = own_voice(request, vid)
    error = ("Voice cloning is not available on this server." if not clones.enabled() or v["owner_id"] != u["id"] else
             "Please confirm both statements." if not (own and consent) else
             "These sentences have expired. Open the page again for new ones." if v["status"] != "draft" or
             v["created_at"] < db.now() - clones.FRESH_S else
             "Give the voice a name." if not name.strip() else None)
    data = b"" if error else file.file.read(10 * 1024 ** 2 + 1)
    error = error or ("The recording is empty or larger than 10 MB." if not 1000 < len(data) <= 10 * 1024 ** 2 else None)
    if error:
        return PlainTextResponse(error, 400)
    clones.save(vid, "recording", data)
    db.run("update voices set name=?, status='waiting' where id=?", name.strip()[:60], vid)
    return go(f"/app/studio/{vid}")  # the Studio shows the check, then the listing editor


@app.get("/app/voices/{vid}")
def voice_page(request: Request, vid: int):
    own_voice(request, vid)
    return go(f"/app/studio/{vid}")  # a voice lives in the Studio now


# ---------------------------------------------------------------- Voice Studio: the publisher's console (record → check → listing → review → live)

@app.get("/app/studio")
def studio(request: Request):
    u = auth.require_user(request)
    reviews = db.all_("select voice_reviews.*, voices.name voice, users.name who from voice_reviews join voices on voices.id=voice_id "
                      "join users on users.id=voice_reviews.user_id where voices.owner_id=? order by voice_reviews.created_at desc limit 6",
                      u["id"])
    return page(request, "studio.html", user=u, voices=[{"v": v, "step": clones.step(v)} for v in clones.own_voices(u)],
                k=clones.studio(u), reviews=reviews, RATE=clones.RATE, STEPS=clones.STEPS, cloning=clones.enabled())


def studio_page(request: Request, u, vid: int, status: int = 200, **ctx):
    v = clones.listing(u, vid)
    return page(request, "studio_voice.html", status, user=u, v=v, step=clones.step(v), STEPS=clones.STEPS, RATE=clones.RATE,
                CATS=clones.CATEGORIES, ALLTAGS=clones.TAGS, sample=(clones.folder(vid) / "sample.mp3").exists(),
                **{"form": None, **ctx})


@app.get("/app/studio/{vid}")
def studio_voice(request: Request, vid: int):
    u, v = own_voice(request, vid)
    return go("/app/studio") if v["status"] == "draft" else studio_page(request, u, vid)


@app.post("/app/studio/{vid}")
def studio_save(request: Request, vid: int, action: str = Form("save"), name: str = Form(""), description: str = Form(""),
                category: str = Form(""), chosen: list[str] = Form([], alias="tags"), agree: str = Form("")):
    """Save the listing as a draft, or submit it for review (first time, or again after a rejection: needs the agreement).
    A listed or in-review listing must stay complete."""
    u, v = own_voice(request, vid)
    if v["owner_id"] != u["id"] or v["status"] != "ready":
        raise HTTPException(400)
    submit = action == "submit" and v["shared"] in ("no", "rejected") and not v["source"]  # a voice from a video stays private
    error = ("Give the voice a name." if not name.strip() else
             clones.listing_error(description, category, chosen, complete=submit or v["shared"] in ("listed", "pending")) or
             ("Please tick the agreement to publish." if submit and not agree else None))
    if error:
        return studio_page(request, u, vid, 400, error=error,
                           form={"name": name, "description": description, "category": category, "tags": chosen})
    db.run("update voices set name=?, description=?, category=?, tags=? where id=?",
           name.strip()[:60], description.strip(), category, ",".join(chosen), vid)
    if submit:
        db.run("update voices set shared='pending', shared_at=?, review_note='' where id=?", db.now(), vid)
    return go(f"/app/studio/{vid}?m={'voice-shared' if submit else 'listing-saved'}")


@app.get("/app/voices/{vid}/sample")
def voice_sample(request: Request, vid: int):
    u = auth.require_user(request)
    v = db.one("select * from voices where id=?", vid)
    f = clones.folder(vid) / "sample.mp3"
    if not v or not f.exists() or not (v["owner_id"] == u["id"] or v["shared"] == "listed" or auth.is_admin(u)):
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/mpeg")


@app.post("/app/voices/{vid}/unshare")
def voice_unshare(request: Request, vid: int):
    own_voice(request, vid)
    db.run("update voices set shared='no' where id=?", vid)
    return go(f"/app/studio/{vid}?m=voice-unshared")


@app.post("/app/voices/{vid}/delete")
def voice_delete(request: Request, vid: int):
    own_voice(request, vid)
    clones.delete(vid)
    return go("/app/studio?m=voice-deleted")


# ---------------------------------------------------------------- marketplace: browse, add to my voices, rate

@app.get("/app/market")
def marketplace(request: Request, q: str = "", lang: str = "", cat: str = "", sort: str = "popular"):
    u = auth.require_user(request)
    q, lang = q.strip()[:80], lang if lang in LANGS else ""
    cat, sort = cat if cat in clones.CATEGORIES else "", sort if sort in clones.SORTS else "popular"
    items = clones.market(u, q, lang, cat, sort)
    browsing = not (q or lang or cat)
    return page(request, "market.html", user=u, items=items, q=q, lang=lang, cat=cat, sort=sort, CATS=clones.CATEGORIES,
                featured=items[:3] if browsing and len(items) > 3 else [], cloning=clones.enabled(),
                originals=[v for v in voices() if v["sample"] and (not lang or v["lang"] == lang)])


@app.get("/app/market/{vid}")
def market_listing(request: Request, vid: int):
    u = auth.require_user(request)
    v = clones.listing(u, vid)
    if not v or (v["shared"] != "listed" or v["status"] != "ready") and v["owner_id"] != u["id"] and not auth.is_admin(u):
        raise HTTPException(404)
    reviews = db.all_("select voice_reviews.*, users.name from voice_reviews join users on users.id=user_id "
                      "where voice_id=? order by created_at desc", vid)
    return page(request, "listing.html", user=u, v=v, reviews=reviews, mine=next((r for r in reviews if r["user_id"] == u["id"]), None),
                hist={r["stars"]: r["n"] for r in db.all_("select stars, count(*) n from voice_reviews where voice_id=? group by stars", vid)},
                more=[x for x in clones.market(u) if x["owner_id"] == v["owner_id"] and x["id"] != vid][:4])


def listed_voice(vid: int):
    v = db.one("select * from voices where id=? and status='ready' and shared='listed'", vid)
    if not v:
        raise HTTPException(404)
    return v


@app.post("/app/market/{vid}/add")
def market_add(request: Request, vid: int):
    u = auth.require_user(request)
    listed_voice(vid)
    db.run("insert or ignore into voice_saves(user_id, voice_id, created_at) values(?,?,?)", u["id"], vid, db.now())
    return Response(status_code=204) if request.headers.get("x-fetch") else go(f"/app/market/{vid}?m=voice-added")


@app.post("/app/market/{vid}/remove")
def market_remove(request: Request, vid: int):
    u = auth.require_user(request)
    db.run("delete from voice_saves where user_id=? and voice_id=?", u["id"], vid)
    return Response(status_code=204) if request.headers.get("x-fetch") else go(f"/app/market/{vid}?m=voice-removed")


@app.post("/app/market/{vid}/review")
def market_review(request: Request, vid: int, stars: int = Form(...), body: str = Form("")):
    """One rating per user, by people who added the voice (not its owner); posting again updates it."""
    u = auth.require_user(request)
    v = listed_voice(vid)
    if v["owner_id"] == u["id"] or not 1 <= stars <= 5 or \
            not db.one("select 1 from voice_saves where user_id=? and voice_id=?", u["id"], vid):
        raise HTTPException(400)
    db.run("insert into voice_reviews(voice_id, user_id, stars, body, created_at) values(?,?,?,?,?) on conflict(voice_id, user_id) "
           "do update set stars=excluded.stars, body=excluded.body, created_at=excluded.created_at",
           vid, u["id"], stars, body.strip()[:500], db.now())
    return go(f"/app/market/{vid}?m=review-saved#reviews")


# ---------------------------------------------------------------- admin (users.admin = 1, or emails in DUBBE_ADMINS)

ADMIN_TABS = ["overview", "users", "jobs", "messages", "voices", "evaluation"]


def admin_overview() -> dict:
    now = db.now()
    month = datetime.datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    n = lambda sql, *a: db.one(sql, *a)[0]  # noqa: E731
    days = [(datetime.date.today() - datetime.timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    per_day = {(r[0], r[1]): r[2] for r in db.all_(
        "select 'dub', date(created_at, 'unixepoch', 'localtime') d, count(*) from jobs where created_at>? group by d "
        "union all select 'tool', date(created_at, 'unixepoch', 'localtime') d, count(*) from tasks where created_at>? group by d",
        now - 15 * 86400, now - 15 * 86400)}
    chart = [{"day": d[5:], "dub": per_day.get(("dub", d), 0), "tool": per_day.get(("tool", d), 0)} for d in days]
    return {
        "kpi": {"users": n("select count(*) from users"), "new7": n("select count(*) from users where created_at>?", now - 7 * 86400),
                "unverified": n("select count(*) from users where verified_at is null"),
                "dubs": n("select count(*) from jobs where status='done' and from_stage is null"),
                "redubs": n("select count(*) from jobs where status='done' and from_stage is not null"),
                "tools": n("select count(*) from tasks where status='done'"),
                "failed": n("select count(*) from jobs where status='failed'") + n("select count(*) from tasks where status='failed'"),
                "waiting": n("select count(*) from jobs where status='waiting'") + n("select count(*) from tasks where status='waiting'"),
                "minutes": round(n("select coalesce(sum(minutes),0) from projects where created_at>=?", month) +
                                 n("select coalesce(sum(minutes),0) from tasks where created_at>=?", month), 1),
                "open": n("select count(*) from messages where handled_at is null")},
        "chart": chart, "top": max([c["dub"] + c["tool"] for c in chart] + [1]),
        "by_tool": {k: n("select count(*) from tasks where kind=?", k) for k in TOOLS},
        "signups": db.all_("select * from users order by id desc limit 5"),
        "failures": db.all_("select 'dub' kind, jobs.id, projects.title, jobs.error, jobs.finished_at from jobs join projects "
                            "on projects.id=project_id where jobs.status='failed' union all select kind, id, title, error, "
                            "finished_at from tasks where status='failed' order by finished_at desc limit 5")}


@app.get("/admin")
def admin(request: Request):
    return admin_tab(request, "overview")


@app.get("/admin/{tab}")
def admin_tab(request: Request, tab: str):
    if tab not in ADMIN_TABS:
        raise HTTPException(404)
    u = auth.require_admin(request)
    ctx = {"worker": worker.STATE, "now": db.now()}
    if tab == "overview":
        ctx |= admin_overview()
    elif tab == "users":
        ctx["users"] = db.all_("select users.*, (select count(*) from projects where owner_id=users.id) n_projects, "
                               "(select count(*) from tasks where owner_id=users.id) n_tasks from users order by id desc")
    elif tab == "jobs":
        ctx["jobs"] = db.all_("select jobs.*, projects.title, users.email from jobs join projects on projects.id=project_id "
                              "join users on users.id=owner_id order by jobs.id desc limit 50")
        ctx["tasks"] = db.all_("select tasks.*, users.email from tasks join users on users.id=owner_id order by tasks.id desc limit 50")
    elif tab == "messages":
        ctx["messages"] = db.all_("select * from messages order by handled_at is not null, id desc limit 200")
    elif tab == "voices":
        ctx["clones"] = db.all_("select voices.*, users.email, (select count(*) from voice_uses where voice_id=voices.id) uses "
                                "from voices join users on users.id=owner_id where status<>'draft' "
                                "order by shared='pending' desc, voices.id desc")
    else:
        ctx["evaluation"] = []
        for p in db.all_("select * from projects where deleted_at is null order by id desc"):
            f = worker.work(p) / "segments.json"
            r = ratings.load(worker.work(p)) if f.exists() else []
            if r:
                ctx["evaluation"].append({"p": p, "s": ratings.summarize(r, read_json(f)["segments"])})
    return page(request, "admin.html", user=u, tab=tab, **ctx)


@app.post("/admin/users/{uid}/plan")
def admin_plan(request: Request, uid: int, plan: str = Form(...)):
    auth.require_admin(request)
    if plan in db.PLANS:
        db.run("update users set plan=? where id=?", plan, uid)
    return go("/admin/users?m=saved")


@app.post("/admin/users/{uid}/admin")
def admin_toggle(request: Request, uid: int):
    u = auth.require_admin(request)
    if uid != u["id"]:  # nobody can remove their own admin rights and lock the team out
        db.run("update users set admin=1-admin where id=?", uid)
    return go("/admin/users?m=saved")


@app.post("/admin/users/{uid}/delete")
def admin_delete_user(request: Request, uid: int):
    u = auth.require_admin(request)
    if uid != u["id"]:
        worker.delete_user_files(uid)
        db.run("delete from users where id=?", uid)
    return go("/admin/users?m=removed")


@app.post("/admin/voices/{vid}/{action}")
def admin_voice(request: Request, vid: int, action: str, note: str = Form("")):
    """Review of shared clones: list it, reject it (with a note the publisher sees in the Studio), take it out of the
    marketplace, or delete it (e.g. after a report)."""
    auth.require_admin(request)
    if action == "delete":
        clones.delete(vid)
    elif action in ("listed", "rejected", "no"):
        db.run("update voices set shared=?, review_note=? where id=? and status='ready'",
               action, note.strip()[:300] if action == "rejected" else "", vid)
    else:
        raise HTTPException(404)
    return go("/admin/voices?m=saved")


@app.post("/admin/jobs/{jid}/retry")
def admin_retry(request: Request, jid: int):
    auth.require_admin(request)
    job = db.one("select * from jobs where id=? and status='failed'", jid)
    if job:
        queue(job["project_id"], job["stage"] or job["from_stage"])
    return go("/admin/jobs")


@app.post("/admin/tasks/{tid}/retry")
def admin_task_retry(request: Request, tid: int):
    auth.require_admin(request)
    db.run("update tasks set status='waiting', error=null where id=? and status='failed'", tid)
    return go("/admin/jobs")


@app.post("/admin/messages/{mid}/handled")
def handled(request: Request, mid: int):
    auth.require_admin(request)
    db.run("update messages set handled_at=? where id=?", db.now(), mid)
    return go("/admin/messages")


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("DUBBE_HOST", "127.0.0.1"), port=int(os.environ.get("DUBBE_PORT", "8000")))


if __name__ == "__main__":
    main()
