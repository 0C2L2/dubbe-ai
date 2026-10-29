"""Create a website account that can sign in at once (email already confirmed), e.g. for the team or testers.

    python scripts/create_user.py admin@dubbe.local --admin --name "DUBBE Admin"
    python scripts/create_user.py user1@dubbe.local --name "Test User 1"      # prints a random password

Uses DUBBE_WEB_DATA (default data/web), the same database as dubbe-web. An existing email gets a new password
(all its sessions end) and, with --admin, the admin flag.
"""
import argparse
import secrets

from dubbe.web import auth, db

p = argparse.ArgumentParser(description="Create or reset a DUBBE website account.")
p.add_argument("email")
p.add_argument("--name", default="")
p.add_argument("--password", help="at least 10 characters; random if left out")
p.add_argument("--admin", action="store_true", help="can open /admin and has no plan limits")
a = p.parse_args()

pw = a.password or secrets.token_urlsafe(9)
if len(pw) < 10:
    raise SystemExit("The password needs at least 10 characters.")
db.init()
email = a.email.strip().lower()
old = db.one("select id from users where email=?", email)
if old:
    db.run("update users set pw=?, admin=max(admin, ?), verified_at=coalesce(verified_at, ?) where id=?",
           auth.hash_pw(pw), int(a.admin), db.now(), old["id"])
    auth.end_all_sessions(old["id"])
else:
    db.run("insert into users(email, name, pw, verified_at, created_at, admin) values(?,?,?,?,?,?)",
           email, a.name, auth.hash_pw(pw), db.now(), db.now(), int(a.admin))
print(f"{email}  password: {pw}{'  (admin)' if a.admin else ''}  — {'updated' if old else 'created'} in {db.ROOT / 'dubbe.db'}")
