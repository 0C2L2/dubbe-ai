"""Website: pages render, accounts work end to end, projects stay private, uploads queue a job, subtitles."""
import re
import subprocess

import pytest
from fastapi.testclient import TestClient

from dubbe.web import app as web
from dubbe.web import auth, db, worker


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "ROOT", tmp_path)  # never the real data/web
    monkeypatch.setenv("DUBBE_WORKER", "0")  # no dubbing in tests
    auth.FAILS.clear()
    with TestClient(web.app, follow_redirects=False) as c:
        yield c


def mailed_token(tmp_path, kind: str) -> str:
    last = sorted((tmp_path / "outbox").glob("*.eml"))[-1].read_text(encoding="utf8")
    return re.search(rf"/{kind}\?token=([\w-]+)", last)[1]


def user(email: str, verified: bool = True) -> tuple[int, str]:
    uid = db.run("insert into users(email, pw, verified_at, created_at) values(?,?,?,?)",
                 email, auth.hash_pw("long enough pw"), db.now() if verified else None, db.now())
    return uid, auth.start_session(uid)


def test_public_pages_render(client):
    for path in ["/", "/features", "/translate-video/korean-to-english", "/translate-video/english-to-korean",
                 "/education", "/examples", "/results", "/pricing", "/about", "/contact", "/help", "/safety",
                 "/terms", "/use-policy", "/privacy", "/signup", "/signin", "/forgot"]:
        assert client.get(path).status_code == 200, path
    assert client.get("/no-such-page").status_code == 404
    assert client.get("/app").headers["location"] == "/signin?next=/app"


def test_signup_verify_signin_reset(client, tmp_path):
    r = client.post("/signup", data={"email": "A@x.org", "password": "correct horse", "agree": "1"})
    assert r.headers["location"] == "/app?m=verify-sent"
    assert "confirm your email" in client.get("/app").text
    assert client.get(f"/verify?token={mailed_token(tmp_path, 'verify')}").status_code == 303
    assert db.one("select verified_at from users where email='a@x.org'")["verified_at"]

    client.post("/signout")
    assert client.post("/signin", data={"email": "a@x.org", "password": "wrong one!!"}).status_code == 400
    assert client.post("/signin", data={"email": "a@x.org", "password": "correct horse"}).headers["location"] == "/app"

    client.post("/forgot", data={"email": "a@x.org"})
    t = mailed_token(tmp_path, "reset")
    assert client.post("/reset", data={"token": t, "password": "a new password"}).headers["location"] == "/signin?m=pw-changed"
    assert client.get("/app").status_code == 303  # reset signs out everywhere
    assert client.post("/reset", data={"token": t, "password": "another one!"}).status_code == 400  # link works once
    assert client.post("/signin", data={"email": "a@x.org", "password": "a new password"}).status_code == 303


def test_projects_are_private(client):
    a, sa = user("a@x.org")
    b, sb = user("b@x.org")
    pid = db.run("insert into projects(owner_id, title, src, tgt, keep_bg, slow, minutes, created_at) "
                 "values(?, 'mine', 'ko', 'en', 1, 1, 1, ?)", a, db.now())
    client.cookies.set(auth.COOKIE, sb)
    assert client.get(f"/app/p/{pid}").status_code == 404
    assert client.get(f"/app/p/{pid}/export").status_code == 404
    client.cookies.set(auth.COOKIE, sa)
    assert client.get(f"/app/p/{pid}").status_code == 303  # own project, not dubbed yet
    assert client.get(f"/app/p/{pid}/file/segments.json").status_code == 404  # only listed files are served
    assert client.get(f"/app/p/{pid}/file/..%2F..%2Fdubbe.db").status_code == 404


def test_admin_page_only_for_admins(client):
    _, s = user("someone@x.org")
    client.cookies.set(auth.COOKIE, s)
    assert client.get("/admin").status_code == 404  # does not reveal that the page exists
    uid, s = user("boss@x.org")
    db.run("update users set admin=1 where id=?", uid)
    client.cookies.set(auth.COOKIE, s)
    r = client.get("/admin")
    assert r.status_code == 200 and "Worker" in r.text and "someone@x.org" in r.text


def test_dashboards_and_tools_render(client):
    uid, s = user("u@x.org")
    client.cookies.set(auth.COOKIE, s)
    for path, marker in [("/app", "Welcome back"), ("/app/projects", "Projects"), ("/app/tts", "Generate speech"),
                         ("/app/stt", "Transcribe"), ("/app/translate", "Translate"), ("/app/isolate", "Separate"),
                         ("/app/history", "History"), ("/app/voices", "Preset voices")]:
        r = client.get(path)
        assert r.status_code == 200 and marker in r.text, path
    assert "Spanish, from the American preset" in client.get("/app/voices?lang=es").text  # every preset, in any language


def test_tools_queue_tasks_for_their_owner_only(client):
    uid, s = user("u@x.org")
    client.cookies.set(auth.COOKIE, s)
    assert client.post("/app/tts", data={"text": "", "lang": "en", "voice": "af_heart"}).status_code == 400
    assert client.post("/app/tts", data={"text": "Hi.", "lang": "en", "voice": "nobody"}).status_code == 400
    r = client.post("/app/tts", data={"text": "[slow] Hello there. [question] Ready", "lang": "en", "voice": "af_heart"})
    assert r.status_code == 303 and r.headers["location"] == "/app/tasks/1"
    t = db.one("select * from tasks where id=1")
    assert t["kind"] == "tts" and t["status"] == "waiting" and '"voice": "af_heart"' in t["params"]
    r = client.post("/app/translate", data={"text": "안녕하세요.", "src": "ko", "tgt": "en"})
    assert r.headers["location"] == "/app/tasks/2"
    assert client.post("/app/isolate", data={"rights": "1"}, files={"file": ("a.txt", b"x")}).status_code == 400  # not media
    assert "Waiting in the queue" in client.get("/app/tasks/1").text
    assert client.get("/app/tasks/1/file/speech.mp3").status_code == 404  # no result yet: nothing is served
    _, other = user("o@x.org")
    client.cookies.set(auth.COOKIE, other)
    assert client.get("/app/tasks/1").status_code == 404


def test_tts_tags_are_read_per_sentence():
    from dubbe.web.tools import parse_tags, split_sentences
    assert split_sentences("[slow] Hello there. [question] Ready\nNext line!") == ["[slow] Hello there.", "[question] Ready", "Next line!"]
    assert parse_tags("Well [laugh] that is [nope] funny [soft]") == ("Well that is funny", ["soft", "laugh"], ["nope"])


def test_tts_tags_glued_to_punctuation_and_left_alone():
    from dubbe.web.tools import sentences
    # a user's text: no space after "????", and tags after the last sentence (before: all on one sentence)
    assert sentences("What????[slow] [loud] [laugh] are you all insane???[angry] [cough] [loud]") == [
        ("What????", [], []), ("are you all insane???", ["slow", "loud", "angry", "laugh", "cough"], [])]
    assert sentences("[soft]\nHello. [bad]") == [("Hello.", ["soft"], ["bad"])]


def test_admin_manages_users_but_not_itself(client):
    aid, sa = user("boss@x.org")
    db.run("update users set admin=1 where id=?", aid)
    uid, _ = user("u@x.org")
    client.cookies.set(auth.COOKIE, sa)
    for tab in ("", "/users", "/jobs", "/messages", "/evaluation"):
        assert client.get("/admin" + tab).status_code == 200, tab
    client.post(f"/admin/users/{uid}/plan", data={"plan": "pro"})
    client.post(f"/admin/users/{uid}/admin")
    assert dict(db.one("select plan, admin from users where id=?", uid)) == {"plan": "pro", "admin": 1}
    client.post(f"/admin/users/{aid}/admin")  # cannot remove its own admin rights
    client.post(f"/admin/users/{aid}/delete")  # nor delete itself
    assert db.one("select admin from users where id=?", aid)["admin"] == 1
    client.post(f"/admin/users/{uid}/delete")
    assert db.one("select 1 from users where id=?", uid) is None


def test_cross_site_post_refused(client):
    r = client.post("/contact", data={"email": "a@x.org"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_contact_saves_and_limits(client):
    form = {"email": "a@x.org", "topic": "Support", "body": "Hello", "agree": "1"}
    for _ in range(3):
        assert client.post("/contact", data=form).headers["location"] == "/contact?m=sent"
    assert client.post("/contact", data=form).status_code == 400  # 4th within an hour
    assert db.one("select count(*) n from messages")["n"] == 3


def test_upload_queues_a_job(client, tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=64x64:rate=10",
                    "-f", "lavfi", "-i", "sine=duration=2", "-shortest", str(clip)], check=True)
    _, s = user("a@x.org")
    client.cookies.set(auth.COOKIE, s)
    form = {"src": "ko", "tgt": "en", "keep_bg": "1", "rights": "1"}
    assert client.post("/app/new", data=form, files={"file": ("x.webm", b"x")}).status_code == 400
    r = client.post("/app/new", data=form, files={"file": ("lecture.mp4", clip.read_bytes(), "video/mp4")})
    assert r.headers["location"] == "/app/jobs/1"
    assert db.one("select status from jobs where id=1")["status"] == "waiting"
    assert abs(db.one("select minutes from projects")["minutes"] - 2 / 60) < 0.01
    assert db.one("select voice from projects")["voice"] == "" and "--voice" not in worker.command(db.one("select * from projects"), None)
    # a voice chosen at upload: offered on the form, checked, stored, passed to the pipeline
    assert "Automatic — matched to the speaker" in client.get("/app/new").text
    files = {"file": ("lecture.mp4", clip.read_bytes(), "video/mp4")}
    assert client.post("/app/new", data={**form, "voice": "nobody"}, files=files).status_code == 400
    assert client.post("/app/new", data={**form, "voice": "clone:99"}, files=files).status_code == 400  # not yours, not added
    client.post("/app/new", data={**form, "voice": "af_bella"}, files=files)
    p = db.one("select * from projects order by id desc limit 1")
    assert p["voice"] == "af_bella" and worker.command(p, None)[-2:] == ["--voice", "af_bella"]


def test_media_routes_serve_only_known_items(client, tmp_path):
    (tmp_path / "samples").mkdir()
    for name in ("af_heart", "secret"):
        (tmp_path / "samples" / f"{name}.wav").write_bytes(b"RIFF")
    assert client.get("/samples/af_heart").status_code == 200
    assert client.get("/samples/secret").status_code == 404  # a file, but not a preset voice
    assert client.get("/samples/..%2Fdubbe.db").status_code == 404
    assert client.get("/examples/nope/frame/1").status_code == 404
    assert client.get("/examples/nope/tts/1").status_code == 404


def test_video_is_the_file_not_the_work_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "ROOT", tmp_path)
    (worker.folder(1) / "video.ko-en").mkdir(parents=True)  # the pipeline's work folder sorts first
    (worker.folder(1) / "video.mp4").write_bytes(b"x")
    assert worker.video(1).name == "video.mp4"


def test_subtitles():
    segs = [{"start": 1.0, "end": 2.0, "placed_start": 1.0, "tts_dur": 1.5, "stretch": 1.0, "tgt_text": "Hi.", "src_text": "안녕."},
            {"start": 3661.5, "end": 3662.0, "tts_dur": 0.5, "stretch": 1.0, "tgt_text": "", "src_text": "네."}]
    assert web.subtitles(segs, "tgt_text") == "1\n00:00:01,000 --> 00:00:02,500\nHi.\n"
    assert web.subtitles(segs, "src_text", vtt=True).endswith("01:01:01.500 --> 01:01:02.000\n네.\n")


def test_voice_clone_consent_sharing_and_permissions(client, tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    from dubbe.web import clones
    monkeypatch.setenv("DUBBE_VOICE_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(clones, "enabled", lambda: True)  # the web part does not need the Chatterbox environment
    oid, so = user("owner@x.org")
    other, sx = user("other@x.org")
    owner_u, other_u = (db.one("select * from users where id=?", i) for i in (oid, other))
    client.cookies.set(auth.COOKIE, so)
    assert client.get("/app/voices/new?lang=en").status_code == 200
    v = db.one("select * from voices where owner_id=?", oid)
    assert len(re.findall(r"[.?!]", v["script"])) == 3  # three sentences, picked now
    files = {"file": ("recording.webm", b"x" * 5000, "audio/webm")}
    assert client.post(f"/app/voices/{v['id']}/record", data={"name": "Me"}, files=files).status_code == 400  # no consent
    r = client.post(f"/app/voices/{v['id']}/record", data={"name": "Me", "own": "1", "consent": "1"}, files=files)
    assert r.status_code == 303 and db.one("select status from voices where id=?", v["id"])["status"] == "waiting"
    stored = (tmp_path / "voices" / str(v["id"]) / "recording.enc").read_bytes()
    assert b"x" * 100 not in stored and clones.load(v["id"], "recording") == b"x" * 5000  # encrypted at rest
    db.run("update voices set status='ready' where id=?", v["id"])  # as if the consent check passed
    key = f"clone:{v['id']}"
    assert clones.can_use(owner_u, key) and not clones.can_use(other_u, key)
    (tmp_path / "voices" / str(v["id"]) / "reference.enc").write_bytes((tmp_path / "voices" / str(v["id"]) / "recording.enc").read_bytes())
    first_dub = tmp_path / "projects" / "9" / "video.ko-en" / "voice_prompt.wav"  # work folder not made yet
    assert clones.write_reference(owner_u, key, first_dub) and first_dub.read_bytes() == b"x" * 5000
    assert not clones.write_reference(other_u, key, tmp_path / "x.wav")  # not theirs, not listed

    client.cookies.set(auth.COOKIE, sx)  # someone else: not usable, not visible, until listed
    assert client.post("/app/tts", data={"text": "Hi.", "lang": "en", "voice": key}).status_code == 400
    assert client.get(f"/app/voices/{v['id']}").status_code == 404
    client.cookies.set(auth.COOKIE, so)  # Voice Studio: draft, then submit (agreement + complete listing), review
    studio = f"/app/studio/{v['id']}"
    assert client.get("/app/studio").status_code == 200 and "Me" in client.get(studio).text
    assert client.post(studio, data={"name": "Me", "action": "save"}).status_code == 303  # a draft may be empty
    listing = {"name": "Me", "description": "A calm narrator voice for lectures.", "category": "Education", "tags": ["calm", "clear"]}
    assert client.post(studio, data={**listing, "action": "submit"}).status_code == 400  # needs the agreement
    assert client.post(studio, data={"name": "Me", "action": "submit", "agree": "1"}).status_code == 400  # and a full listing
    assert client.post(studio, data={**listing, "tags": ["calm", "clear", "deep", "warm"], "action": "save"}).status_code == 400
    client.post(studio, data={**listing, "action": "submit", "agree": "1"})
    assert not clones.can_use(other_u, key)  # in review
    aid, sa = user("boss@x.org")
    db.run("update users set admin=1 where id=?", aid)
    client.cookies.set(auth.COOKIE, sa)
    assert client.get("/admin/voices").status_code == 200
    client.post(f"/admin/voices/{v['id']}/rejected", data={"note": "Too quiet, please record again"})
    client.cookies.set(auth.COOKIE, so)
    assert "Too quiet, please record again" in client.get(studio).text  # the publisher sees why
    client.post(studio, data={**listing, "action": "submit", "agree": "1"})
    client.cookies.set(auth.COOKIE, sa)
    client.post(f"/admin/voices/{v['id']}/listed")

    client.cookies.set(auth.COOKIE, sx)  # the store front: search and filters find it, "Get" adds it to the pickers
    assert "Me" in client.get("/app/market?q=narrator&lang=en&cat=Education&sort=rating").text
    assert "Me" not in client.get("/app/market?q=zzz").text and "Me" not in client.get("/app/market?cat=Characters").text
    assert client.get(f"/app/market/{v['id']}").status_code == 200 and clones.can_use(other_u, key)
    assert client.post("/app/tts", data={"text": "Hi.", "lang": "en", "voice": key}).status_code == 400  # not added yet
    assert client.post(f"/app/market/{v['id']}/review", data={"stars": 5}).status_code == 400  # only after getting it
    assert client.post(f"/app/market/{v['id']}/add", headers={"x-fetch": "1"}).status_code == 204  # stays on the page
    assert "Me" in client.get("/app/voices").text and "Trending in the Voice Marketplace" in client.get("/app").text
    assert client.post("/app/tts", data={"text": "Hi.", "lang": "ko", "voice": key}).status_code == 303  # any language
    client.post(f"/app/market/{v['id']}/review", data={"stars": 4, "body": "Clear."})
    client.post(f"/app/market/{v['id']}/review", data={"stars": 5, "body": "Very clear."})  # updates, one per user
    lv = clones.listing(other_u, v["id"])
    assert (lv["rating"], lv["reviews"], lv["saves"], lv["saved"]) == (5, 1, 1, 1) and "Very clear." in client.get(f"/app/market/{v['id']}").text
    clones.record_use(key, other, 2000, "tts")
    assert clones.stats(db.one("select * from voices where id=?", v["id"]))["earn"] == 0.06  # 2,000 characters at $0.03/1k

    client.cookies.set(auth.COOKIE, so)
    assert client.post(f"/app/market/{v['id']}/review", data={"stars": 5}).status_code == 400  # not your own voice
    client.cookies.set(auth.COOKIE, so)
    client.post(f"/app/voices/{v['id']}/unshare")
    assert not clones.can_use(other_u, key)  # stopped sharing: no new uses
    client.post("/app/settings", data={"action": "delete", "current": "long enough pw"})
    assert not (tmp_path / "voices" / str(v["id"])).exists() and not db.one("select 1 from voices where id=?", v["id"])


def test_speakers_in_the_editor_and_cloning_a_speaker_only_with_consent(client, tmp_path, monkeypatch):
    import json
    import numpy as np
    import soundfile as sf
    from cryptography.fernet import Fernet
    from dubbe.web import clones
    uid, s = user("dub@x.org")
    client.cookies.set(auth.COOKIE, s)
    pid = db.run("insert into projects(owner_id, title, src, tgt, keep_bg, slow, minutes, created_at) values(?,?,?,?,?,?,?,?)",
                 uid, "Scene", "ko", "en", 1, 1.0, 0.2, db.now())
    w = worker.work(db.one("select * from projects where id=?", pid))
    w.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=12:size=64x64:rate=10",
                    "-f", "lavfi", "-i", "sine=duration=12", "-shortest", str(w / "dubbed.mp4")], check=True)
    sf.write(w / "vocals.wav", (0.3 * np.sin(np.arange(12 * 16000) / 16000 * 2 * np.pi * 180)).astype("float32"), 16000)
    segs = [{"id": 1, "start": 0.0, "end": 3.0, "speaker": "S1", "src_text": "안녕", "tgt_text": "Hello.", "edited": False, "tags": []},
            {"id": 2, "start": 3.0, "end": 12.0, "speaker": "S2", "src_text": "네", "tgt_text": "Yes, I know.", "edited": False, "tags": []}]
    (w / "segments.json").write_text(json.dumps({"segments": segs, "speakers": {"S1": {"name": "Speaker 1", "voice": "af_heart"},
                                                                                "S2": {"name": "Speaker 2", "voice": "am_adam"}}}), encoding="utf8")
    page_ = client.get(f"/app/p/{pid}").text
    assert "2 detected" in page_ and "Speaker 2" in page_
    client.post(f"/app/p/{pid}/speakers/S2", data={"name": "Jesse"})
    assert client.post(f"/app/p/{pid}/speakers/S1", data={"voice": "nobody"}).status_code == 400
    client.post(f"/app/p/{pid}/speakers/S1", data={"name": "Walter", "voice": "af_bella"})
    data = json.loads((w / "segments.json").read_text(encoding="utf8"))
    assert data["speakers"]["S2"]["name"] == "Jesse" and data["speakers"]["S1"]["voice"] == "af_bella" and data["speakers_edited"]
    assert "Walter: Hello." in client.get(f"/app/p/{pid}/download/tgt.txt").text  # transcript by speaker
    # cloning a speaker of the video: hidden without the key, refused without consent, made with it - project only
    assert client.post(f"/app/p/{pid}/speakers/S2/clone", data={"consent": "1"}).status_code == 404
    monkeypatch.setenv("DUBBE_VOICE_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(clones, "enabled", lambda: True)
    assert "consent-needed" in client.post(f"/app/p/{pid}/speakers/S2/clone", data={}).headers["location"]
    assert "too-little-speech" in client.post(f"/app/p/{pid}/speakers/S1/clone", data={"consent": "1"}).headers["location"]  # 3 s
    assert "speaker-cloned" in client.post(f"/app/p/{pid}/speakers/S2/clone", data={"consent": "1"}).headers["location"]
    data = json.loads((w / "segments.json").read_text(encoding="utf8"))
    f = clones.speaker_file(pid, "S2")
    assert data["speakers"]["S2"]["voice"] == "video:S2" and data["speakers"]["S2"]["clone_consent"]["by"] == "dub@x.org"
    assert f.exists() and not f.read_bytes().startswith(b"RIFF") and not db.one("select 1 from voices")  # encrypted, not a library voice
    assert clones.write_speaker_reference(pid, "video:S2", tmp_path / "p.wav") and (tmp_path / "p.wav").read_bytes()[:4] == b"RIFF"
    # a wrong detection: move a sentence, merge a person split in two
    client.post(f"/app/p/{pid}/s/1", data={"text": "Hello.", "speaker": "S2"})
    assert json.loads((w / "segments.json").read_text(encoding="utf8"))["segments"][0]["speaker"] == "S2"
    client.post(f"/app/p/{pid}/speakers/S2", data={"merge": "S1"})
    data = json.loads((w / "segments.json").read_text(encoding="utf8"))
    assert {x["speaker"] for x in data["segments"]} == {"S1"} and list(data["speakers"]) == ["S1"]
    client.post(f"/app/p/{pid}/s/2", data={"text": "Yes, I know.", "speaker": "new"})  # two voices detected as one: split
    data = json.loads((w / "segments.json").read_text(encoding="utf8"))
    assert data["segments"][1]["speaker"] == "S2" and data["speakers"]["S2"]["voice"] != data["speakers"]["S1"]["voice"]
    r = client.post(f"/app/p/{pid}/detect-speakers")  # start over: detection runs again, the old clone may be someone else now
    data = json.loads((w / "segments.json").read_text(encoding="utf8"))
    assert r.status_code == 303 and "speakers_edited" not in data and not f.exists()
    assert db.one("select from_stage from jobs where project_id=? order by id desc limit 1", pid)["from_stage"] == "speakers"
    db.run("update jobs set status='done' where project_id=?", pid)
    client.post(f"/app/p/{pid}/rerun")  # newer recognition / translation models: from the transcript on
    assert db.one("select from_stage from jobs where project_id=? order by id desc limit 1", pid)["from_stage"] == "asr"
    worker.delete_project(pid)
    assert not f.exists()  # the speaker's clone goes with the project


def test_speaker_detection_tool_names_speakers_and_clones_one_privately_with_consent(client, monkeypatch):
    import json
    import numpy as np
    import soundfile as sf
    from cryptography.fernet import Fernet
    from dubbe.web import clones, tools
    uid, s = user("spk@x.org")
    client.cookies.set(auth.COOKIE, s)
    assert "Find speakers" in client.get("/app/speakers").text
    tid = db.run("insert into tasks(owner_id, kind, title, params, status, created_at) values(?,?,?,?,?,?)",
                 uid, "speakers", "Scene", json.dumps({"src": "en"}), "done", db.now())
    out = tools.folder(tid)
    out.mkdir(parents=True)
    sf.write(out / "vocals44.wav", (0.3 * np.sin(np.arange(14 * 44100) / 44100 * 2 * np.pi * 180)).astype("float32"), 44100)
    segs = [{"id": 1, "start": 0.0, "end": 3.0, "speaker": "S1", "src_text": "Hello."},
            {"id": 2, "start": 3.0, "end": 13.0, "speaker": "S2", "src_text": "Yes, I know."}]
    (out / "segments.json").write_text(json.dumps({"segments": segs, "duration": 14.0, "speakers": {
        "S1": {"name": "Speaker 1"}, "S2": {"name": "Speaker 2"}}}), encoding="utf8")
    db.run("update tasks set result=? where id=?", json.dumps(tools.speaker_files(out)), tid)
    assert "Who speaks when" in client.get(f"/app/tasks/{tid}").text
    client.post(f"/app/tasks/{tid}/speakers/S2", data={"name": "Jesse"})  # the name goes into the transcript and subtitles
    assert "[0:03.0] Jesse: Yes, I know." in (out / "transcript.txt").read_text(encoding="utf8")
    assert "Jesse: Yes, I know." in (out / "transcript.srt").read_text(encoding="utf8")
    assert client.post(f"/app/tasks/{tid}/speakers/S9", data={"name": "x"}).status_code == 404
    monkeypatch.setenv("DUBBE_VOICE_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(clones, "enabled", lambda: True)
    assert "consent-needed" in client.post(f"/app/tasks/{tid}/speakers/S2/clone", data={}).headers["location"]
    assert "too-little-speech" in client.post(f"/app/tasks/{tid}/speakers/S1/clone", data={"consent": "1"}).headers["location"]
    r = client.post(f"/app/tasks/{tid}/speakers/S2/clone", data={"consent": "1", "name": "Jesse"})
    v = db.one("select * from voices")
    assert r.headers["location"] == f"/app/studio/{v['id']}" and v["status"] == "waiting" and v["source"] == f"video:{tid}"
    assert v["script"] == "Yes, I know." and clones.load(v["id"], "recording")[:4] == b"RIFF"  # checked like a recording
    db.run("update voices set status='ready' where id=?", v["id"])
    client.post(f"/app/studio/{v['id']}", data={"action": "submit", "name": "Jesse", "description": "A calm voice for stories.",
                                                "category": "Narration", "tags": "calm", "agree": "1"})
    assert db.one("select shared from voices")["shared"] == "no"  # a voice from a video is never published
    _, other = user("o@x.org")
    client.cookies.set(auth.COOKIE, other)
    assert client.post(f"/app/tasks/{tid}/speakers/S2/clone", data={"consent": "1"}).status_code == 404


def test_subtitles_tool_names_speakers_burns_on_request_and_dub_captions(client):
    import json
    from dubbe.web import tools
    uid, s = user("cap@x.org")
    client.cookies.set(auth.COOKIE, s)
    assert "Make subtitles" in client.get("/app/captions").text
    tid = db.run("insert into tasks(owner_id, kind, title, params, status, created_at) values(?,?,?,?,?,?)",
                 uid, "captions", "Scene", json.dumps({"src": "en", "to": "ko"}), "done", db.now())
    out = tools.folder(tid)
    out.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=4:size=64x64:rate=10",
                    "-f", "lavfi", "-i", "sine=duration=4", "-shortest", str(out / "input.mp4")], check=True)
    segs = [{"id": 1, "start": 0.0, "end": 1.5, "speaker": "S1", "src_text": "Hello.", "tgt_text": "안녕."},
            {"id": 2, "start": 2.0, "end": 3.5, "speaker": "S2", "src_text": "Hi.", "tgt_text": "응."}]
    (out / "segments.json").write_text(json.dumps({"segments": segs, "speakers": {"S1": {"name": "Speaker 1"},
                                                                                  "S2": {"name": "Speaker 2"}}}), encoding="utf8")
    p = {"src": "en", "to": "ko"}
    db.run("update tasks set result=? where id=?", json.dumps(tools.caption_files(out, p, tid)), tid)
    page_ = client.get(f"/app/tasks/{tid}").text
    assert 'srclang="ko"' in page_ and "Burn in" in page_  # the upload plays with both caption tracks
    client.post(f"/app/tasks/{tid}/speakers/S2", data={"name": "Jesse"})  # the captions are written again with the name
    assert "<v.s2 Jesse>Hi.</v>" in (out / "en.vtt").read_text(encoding="utf8")
    assert client.get(f"/app/tasks/{tid}/file/en.vtt").headers["content-type"].startswith("text/vtt")
    assert client.post(f"/app/tasks/{tid}/burn", data={"lang": "fr"}).status_code == 404  # not one of its languages
    client.post(f"/app/tasks/{tid}/burn", data={"lang": "ko"})
    t = db.one("select * from tasks where id=?", tid)
    assert t["status"] == "waiting" and json.loads(t["params"])["burn"] == "ko"
    pid = db.run("insert into projects(owner_id, title, src, tgt, keep_bg, slow, minutes, created_at) values(?,?,?,?,?,?,?,?)",
                 uid, "Dub", "en", "ko", 1, 1.0, 0.1, db.now())
    w = worker.work(db.one("select * from projects where id=?", pid))
    w.mkdir(parents=True)
    (w / "segments.json").write_text(json.dumps({"segments": segs, "speakers": {"S1": {"name": "A"}, "S2": {"name": "B"}}}), encoding="utf8")
    assert client.post(f"/app/p/{pid}/captions", data={"lang": "tgt"}).status_code == 404  # the dub is not finished
    db.run("insert into jobs(project_id, status, created_at) values(?, 'done', ?)", pid, db.now())
    r = client.post(f"/app/p/{pid}/captions", data={"lang": "tgt"})
    task = db.one("select * from tasks where kind='captions' order by id desc limit 1")
    assert r.headers["location"] == f"/app/tasks/{task['id']}" and json.loads(task["params"]) == {"project": pid, "src": "en", "to": "ko", "burn": "ko"}
    assert '<font color="#FFFF00">응.</font>' in client.get(f"/app/p/{pid}/download/tgt.color.srt").text
    assert "Style: S2,Malgun Gothic" in client.get(f"/app/p/{pid}/download/tgt.ass").text
