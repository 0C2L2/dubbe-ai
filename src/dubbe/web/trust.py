"""Trust and safety for the features that use a real person's voice: cloning your own voice, cloning a speaker from a
video, publishing to the Marketplace, and dubbing or speaking with those voices (agreed with the team, 2026-11-07).

- phone: one verified phone per account before any cloning. Beta: the code is not sent by SMS but written to the
  local outbox (send_sms); a real provider (Twilio Verify, Naver SENS) only has to replace send_sms.
- words: sentences spoken in a real person's voice are checked for swear words (LDNOOBW lists, 19 of the 24 languages)
  and scam patterns (links, phone / account / card numbers, crypto wallets, money requests). Flagged for the admin,
  never blocked - lies cannot be caught by words; a report from the person covers that.
- evidence: who did what with a real person's voice (account, verified phone, IP, time), kept RETAIN_DAYS days, given
  out only for an official request (export); a reported account can be frozen, nothing deleted, until it is resolved.
"""
import hashlib
import hmac
import json
import re
import secrets
import time
from functools import lru_cache
from pathlib import Path

from . import db

CODE_MINUTES, MAX_TRIES, MAX_CODES_PER_HOUR = 10, 5, 5
RETAIN_DAYS = 90
SMS_BETA = True  # the code is written to data/web/outbox/, not sent


# ---------------------------------------------------------------- phone

def normalize(raw: str) -> str | None:
    """+<country><number> (E.164), or None. A number starting with 0 is read as Korean (010-1234-5678)."""
    n = re.sub(r"[^\d+]", "", raw or "")
    if n.startswith("00"):
        n = "+" + n[2:]
    elif n.startswith("0"):
        n = "+82" + n[1:]
    return n if re.fullmatch(r"\+[1-9]\d{7,14}", n) else None


def mask(phone: str | None) -> str:
    return phone[:3] + "*" * max(0, len(phone) - 7) + phone[-4:] if phone else ""


def verified(u) -> bool:
    return bool(u and u["phone_verified_at"])


def _hash(uid: int, phone: str, code: str) -> str:
    return hashlib.sha256(f"{uid}:{phone}:{code}".encode()).hexdigest()


def send_sms(phone: str, text: str) -> None:
    """Beta: written to the outbox like the local mail (auth.send_mail). A provider replaces this one function."""
    out = db.ROOT / "outbox"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 10 ** 9:09d}.sms.txt").write_text(
        f"To: {phone}\n\n{text}\n", encoding="utf8")


def send_code(u, raw: str) -> str | None:
    """Send a 6-digit code to the number; the error to show, or None."""
    phone = normalize(raw)
    if not phone:
        return "Enter the number with its country code (for example +82 10 1234 5678), or a Korean number starting with 0."
    if db.one("select id from users where phone=? and phone_verified_at is not null and id!=?", phone, u["id"]):
        return "This number already verifies another account."
    hour = db.now() - 3600
    if db.one("select count(*) n from phone_codes where (user_id=? or phone=?) and created_at>?", u["id"], phone, hour)["n"] >= MAX_CODES_PER_HOUR:
        return "Too many codes in an hour. Try again later."
    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.run("insert into phone_codes(user_id, phone, code_hash, expires_at, created_at) values(?,?,?,?,?)",
           u["id"], phone, _hash(u["id"], phone, code), db.now() + CODE_MINUTES * 60, db.now())
    send_sms(phone, f"Your DUBBE code is {code}. It works for {CODE_MINUTES} minutes. Do not share it.")
    return None


def check_code(u, code: str) -> str | None:
    """Verify the newest code; the error to show, or None (the phone is then the account's)."""
    c = db.one("select * from phone_codes where user_id=? order by id desc limit 1", u["id"])
    if not c or c["expires_at"] < db.now():
        return "This code has expired. Ask for a new one."
    if c["tries"] >= MAX_TRIES:
        return "Too many wrong tries. Ask for a new code."
    if not hmac.compare_digest(c["code_hash"], _hash(u["id"], c["phone"], (code or "").strip())):
        db.run("update phone_codes set tries=tries+1 where id=?", c["id"])
        return "That code is not right."
    if db.one("select id from users where phone=? and phone_verified_at is not null and id!=?", c["phone"], u["id"]):
        return "This number already verifies another account."
    db.run("update users set phone=?, phone_verified_at=? where id=?", c["phone"], db.now(), u["id"])
    db.run("delete from phone_codes where user_id=?", u["id"])
    return None


# ---------------------------------------------------------------- words

def real_voice(voice: str | None) -> bool:
    """A real person's voice: a clone of your own or someone's (clone:<id>, Marketplace too) or a speaker of the video."""
    return (voice or "").startswith(("clone:", "video:"))


@lru_cache(maxsize=1)
def _lists() -> dict:
    words = json.loads((Path(__file__).with_name("badwords.json")).read_text(encoding="utf8"))
    out = {}
    for lang, ws in words.items():
        if lang.startswith("_"):
            continue
        alt = "|".join(re.escape(w) for w in sorted(ws, key=len, reverse=True))
        out[lang] = re.compile(alt if lang in ("ja", "ko", "zh") else rf"(?<!\w)(?:{alt})(?!\w)", re.I)  # no spaces in CJK
    return out


SCAM = [  # (what, pattern) - language-free first, then money requests in the languages most of our users speak
    ("link", re.compile(r"https?://\S+|www\.\S+|\b[a-z0-9-]+\.(?:com|net|org|io|kr|ru|uz|kz|me|ly|link|xyz|shop|top)\b", re.I)),
    ("phone or account number", re.compile(r"(?<!\d)\+?\d(?:[\s().-]?\d){8,18}(?!\d)")),
    ("crypto wallet", re.compile(r"\b(?:0x[a-fA-F0-9]{40}|bc1[a-z0-9]{25,59}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")),
    ("money request", re.compile(r"\b(?:send|transfer|wire)\s+(?:me\s+|us\s+)?(?:the\s+|your\s+)?(?:money|funds|payment|bitcoin|crypto)\b"
                                 r"|\bgift\s+cards?\b|\bbank\s+account\b|\bverification\s+code\b"
                                 r"|송금|입금해|계좌|이체|인증번호|비밀번호"
                                 r"|переведите|перевод\w* денег|номер карты|код из смс", re.I)),
]


def check(text: str, lang: str) -> list[str]:
    """What is wrong with a sentence spoken in a real person's voice: 'swear word', 'link', ... (empty: nothing)."""
    text = text or ""
    found = ["swear word"] if lang in _lists() and _lists()[lang].search(text) else []
    return found + [what for what, rx in SCAM if rx.search(text)]


def flag(kind: str, ref: int, uid: int, hits: list[tuple[str, list[str]]]) -> int:
    """Record what was found for the admin (one open row per dub or task); returns how many sentences."""
    db.run("delete from flags where kind=? and ref=? and handled_at is null", kind, ref)
    if hits:
        sample = " · ".join(f"{', '.join(why)}: {text[:80]}" for text, why in hits[:3])
        db.run("insert into flags(kind, ref, user_id, n, sample, created_at) values(?,?,?,?,?,?)",
               kind, ref, uid, len(hits), sample, db.now())
    return len(hits)


def flag_dub(p, data: dict) -> int:
    """After a dub: mark the sentences spoken in a real person's voice that contain swear words or scam patterns."""
    voices = {sp: v.get("voice") for sp, v in (data.get("speakers") or {}).items()}
    hits = []
    for s in data.get("segments", []):
        why = check(s.get("tgt_text"), p["tgt"]) if real_voice(voices.get(s.get("speaker", "S1"))) else []
        if why:
            s["word_flag"] = why
            hits.append((s.get("tgt_text") or "", why))
        else:
            s.pop("word_flag", None)
    return flag("dub", p["id"], p["owner_id"], hits)


# ---------------------------------------------------------------- evidence

def log(u, what: str, ref: str = "", request=None) -> None:
    """Who did what with a real person's voice; older entries than RETAIN_DAYS go."""
    ip = request.client.host if request is not None and request.client else ""
    db.run("insert into evidence(user_id, what, ref, ip, phone, created_at) values(?,?,?,?,?,?)",
           u["id"], what, str(ref), ip, u["phone"] or "", db.now())
    db.run("delete from evidence where created_at<?", db.now() - RETAIN_DAYS * 86400)


def export(uid: int) -> dict:
    """Everything kept about an account, for an official request (police, court) - never for the person who reported."""
    row = lambda r: dict(r) if r else None  # noqa: E731
    u = row(db.one("select id, email, name, created_at, verified_at, phone, phone_verified_at, frozen_at from users where id=?", uid))
    return {"exported_at": db.now(), "account": u,
            "evidence": [dict(r) for r in db.all_("select what, ref, ip, phone, created_at from evidence where user_id=? order by id", uid)],
            "projects": [dict(r) for r in db.all_("select id, title, src, tgt, minutes, own_voices, created_at, deleted_at from projects where owner_id=?", uid)],
            "voices": [dict(r) for r in db.all_("select id, name, lang, status, shared, source, created_at from voices where owner_id=?", uid)],
            "flags": [dict(r) for r in db.all_("select kind, ref, n, sample, created_at, handled_at from flags where user_id=?", uid)]}
