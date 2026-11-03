"""Accounts: passwords (stdlib scrypt), sessions and one-time tokens (only their hashes are stored), email."""
import hashlib
import hmac
import os
import secrets
import smtplib
import time
from email.message import EmailMessage
from urllib.parse import quote

from fastapi import HTTPException, Request

from . import db

COOKIE = "dubbe_session"
SESSION_S = 14 * 86400
# links in emails use this, never the request's Host header (a forged Host would send reset links elsewhere)
SITE_URL = os.environ.get("DUBBE_SITE_URL", "http://127.0.0.1:8000").rstrip("/")
ADMINS = {e.strip().lower() for e in os.environ.get("DUBBE_ADMINS", "").split(",") if e.strip()}


def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    return f"scrypt${salt.hex()}${hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1).hex()}"


def check_pw(pw: str, stored: str) -> bool:
    _, salt, h = stored.split("$")
    return hmac.compare_digest(hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex(), h)


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(user_id: int, kind: str, seconds: int) -> str:
    db.run("delete from tokens where user_id=? and kind=?", user_id, kind)  # only the newest link works
    t = secrets.token_urlsafe(32)
    db.run("insert into tokens values(?,?,?,?)", _h(t), user_id, kind, db.now() + seconds)
    return t


def use_token(t: str, kind: str) -> int | None:
    """Single use: the user id, and the token is gone; None if unknown or expired."""
    row = db.one("delete from tokens where id=? and kind=? returning user_id, expires_at", _h(t), kind)
    return row["user_id"] if row and row["expires_at"] > db.now() else None


def start_session(user_id: int) -> str:
    t = secrets.token_urlsafe(32)
    db.run("insert into sessions values(?,?,?)", _h(t), user_id, db.now() + SESSION_S)
    return t


def end_session(t: str) -> None:
    db.run("delete from sessions where id=?", _h(t))


def end_all_sessions(user_id: int) -> None:
    db.run("delete from sessions where user_id=?", user_id)


def current_user(request: Request):
    t = request.cookies.get(COOKIE)
    if not t:
        return None
    return db.one("select users.* from sessions join users on users.id=sessions.user_id "
                  "where sessions.id=? and sessions.expires_at>?", _h(t), db.now())


def is_admin(user) -> bool:
    """Admin flag in the database (scripts/create_user.py --admin), or the email listed in DUBBE_ADMINS."""
    return bool(user) and (bool(user["admin"]) or user["email"].lower() in ADMINS)


def require_user(request: Request):
    u = current_user(request)
    if not u:
        raise HTTPException(303, headers={"Location": "/signin?next=" + quote(request.url.path)})
    return u


def require_admin(request: Request):
    u = require_user(request)
    if not is_admin(u):
        raise HTTPException(404)
    return u


# ponytail: failed sign-ins kept in memory - resets on restart and is per process; a table if several web processes
FAILS: dict[str, list[float]] = {}


def throttled(key: str) -> bool:
    FAILS[key] = [t for t in FAILS.get(key, []) if t > time.time() - 900]
    return len(FAILS[key]) >= 5  # 5 failed tries in 15 minutes


def failed(key: str) -> None:
    FAILS.setdefault(key, []).append(time.time())


def send_mail(to: str, subject: str, body: str) -> None:
    """SMTP when SMTP_HOST is set. Without it (local testing) the mail goes to data/web/outbox/ and the console."""
    msg = EmailMessage()
    msg["From"] = os.environ.get("DUBBE_MAIL_FROM", "DUBBE <no-reply@localhost>")
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    if os.environ.get("SMTP_HOST"):
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=20) as s:
            s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
        return
    out = db.ROOT / "outbox"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 10 ** 9:09d}.eml").write_text(msg.as_string(), encoding="utf8")
    print(f"[mail, not sent - no SMTP_HOST] to {to}: {subject}\n{body}\n")
