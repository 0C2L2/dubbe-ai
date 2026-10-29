"""The website's database (SQLite, stdlib): users, sessions, one-time tokens, projects, jobs, tool tasks,
contact messages, voice clones and their uses.
Videos, segments.json and ratings stay as files in each project's folder, as with the command line."""
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(os.environ.get("DUBBE_WEB_DATA", "data/web"))  # git-ignored (data/)

# Proposal from docs/website-plan.md section 4. During the beta everyone is on Free; paid plans are a waitlist.
PLANS = {
    "free": {"name": "Free", "price": 0, "minutes": 15, "max_len": 10, "keep_days": 7},
    "creator": {"name": "Creator", "price": 9, "minutes": 120, "max_len": 60, "keep_days": 30},
    "pro": {"name": "Pro", "price": 29, "minutes": 600, "max_len": 180, "keep_days": 90},
}

SCHEMA = """
create table if not exists users(id integer primary key, email text unique not null, name text not null default '',
  pw text not null, verified_at real, plan text not null default 'free', created_at real not null,
  admin integer not null default 0);
create table if not exists sessions(id text primary key, user_id integer not null references users on delete cascade,
  expires_at real not null);
create table if not exists tokens(id text primary key, user_id integer not null references users on delete cascade,
  kind text not null, expires_at real not null);
create table if not exists projects(id integer primary key, owner_id integer not null references users on delete cascade,
  title text not null, src text not null, tgt text not null, keep_bg integer not null, slow real not null,
  minutes real not null, created_at real not null, deleted_at real, voice text not null default '');
create table if not exists jobs(id integer primary key, project_id integer not null references projects on delete cascade,
  from_stage text, status text not null default 'waiting', stage text, error text,
  created_at real not null, started_at real, finished_at real);
create table if not exists tasks(id integer primary key, owner_id integer not null references users on delete cascade,
  kind text not null, title text not null, params text not null, status text not null default 'waiting', result text,
  error text, minutes real not null default 0, created_at real not null, started_at real, finished_at real, deleted_at real);
create table if not exists messages(id integer primary key, name text not null default '', email text not null,
  topic text not null, body text not null, ip text, created_at real not null, handled_at real);
create table if not exists voices(id integer primary key, owner_id integer not null references users on delete cascade,
  name text not null default '', lang text not null, script text not null, status text not null default 'draft',
  heard text, error text, shared text not null default 'no', created_at real not null, checked_at real, shared_at real);
create table if not exists voice_uses(id integer primary key, voice_id integer not null references voices on delete cascade,
  user_id integer not null references users on delete cascade, chars integer not null, kind text not null,
  created_at real not null);
create table if not exists voice_saves(user_id integer not null references users on delete cascade,
  voice_id integer not null references voices on delete cascade, created_at real not null, primary key(user_id, voice_id));
create table if not exists voice_reviews(voice_id integer not null references voices on delete cascade,
  user_id integer not null references users on delete cascade, stars integer not null, body text not null default '',
  created_at real not null, primary key(voice_id, user_id));
"""
# added after the voices table shipped: the marketplace listing of a shared voice, the admin's note on a rejection,
# and source ("video:<task id>" for a speaker cloned from an uploaded video: always private, never listed)
VOICE_LISTING = ("description", "category", "tags", "review_note", "source")


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(ROOT / "dubbe.db", isolation_level=None, timeout=10)  # autocommit; waits if the worker writes
    c.row_factory = sqlite3.Row
    c.execute("pragma foreign_keys=on")
    return c


def init() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as c:
        c.execute("pragma journal_mode=wal")  # web requests read while the worker writes progress
        c.executescript(SCHEMA)
        if "admin" not in {r["name"] for r in c.execute("pragma table_info(users)")}:  # databases made before the column
            c.execute("alter table users add column admin integer not null default 0")
        if "voice" not in {r["name"] for r in c.execute("pragma table_info(projects)")}:  # voice chosen at upload
            c.execute("alter table projects add column voice text not null default ''")
        have = {r["name"] for r in c.execute("pragma table_info(voices)")}
        for col in VOICE_LISTING:
            if col not in have:
                c.execute(f"alter table voices add column {col} text not null default ''")


# ponytail: one short connection per call - fine for SQLite and one worker; PostgreSQL + a pool when deployed
def all_(sql: str, *args) -> list[sqlite3.Row]:
    with closing(connect()) as c:
        return c.execute(sql, args).fetchall()


def one(sql: str, *args) -> sqlite3.Row | None:
    with closing(connect()) as c:
        return c.execute(sql, args).fetchone()


def run(sql: str, *args) -> int:
    with closing(connect()) as c:
        return c.execute(sql, args).lastrowid


def now() -> float:
    return time.time()
