"""Accounts, password hashing and login sessions (schema auth)."""
import base64
import datetime as dt
import hashlib
import hmac
import os
import secrets
import time

SESSION_DAYS = 14
MIN_PASSWORD_LENGTH = 10
_SCRYPT = {"n": 2**15, "r": 8, "p": 1, "maxmem": 2**27, "dklen": 32}

# failed logins per e-mail, in memory: enough to slow down guessing
_MAX_FAILURES, _WINDOW_S = 8, 15 * 60
_failures = {}


def normalise_email(email):
    return email.strip().lower()


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password, stored):
    try:
        _, salt, digest = stored.split("$")
        salt, digest = base64.b64decode(salt), base64.b64decode(digest)
    except ValueError:
        return False
    return hmac.compare_digest(hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT), digest)


def random_password():
    return secrets.token_urlsafe(15)


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def set_password(conn, email, password):
    """Create the account or replace its password. Ends all its sessions."""
    email = normalise_email(email)
    row = conn.execute(
        """
        INSERT INTO auth.account (email, password_hash) VALUES (%s, %s)
        ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash
        RETURNING id
        """,
        [email, hash_password(password)],
    ).fetchone()
    conn.execute("DELETE FROM auth.session WHERE account_id = %s", [row["id"]])
    return row["id"]


def blocked(email):
    now = time.monotonic()
    recent = [t for t in _failures.get(email, []) if now - t < _WINDOW_S]
    _failures[email] = recent
    return len(recent) >= _MAX_FAILURES


def login(conn, email, password):
    """Returns a new session token, or None."""
    email = normalise_email(email)
    account = conn.execute("SELECT id, password_hash FROM auth.account WHERE email = %s", [email]).fetchone()
    # hash even for unknown accounts, so timing does not reveal which e-mails exist
    ok = verify_password(password, account["password_hash"] if account else hash_password(""))
    if not account or not ok:
        _failures.setdefault(email, []).append(time.monotonic())
        return None
    _failures.pop(email, None)
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM auth.session WHERE expires_at < now()")
    conn.execute(
        "INSERT INTO auth.session (token_hash, account_id, expires_at) VALUES (%s, %s, %s)",
        [_token_hash(token), account["id"], dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=SESSION_DAYS)],
    )
    return token


def account_for(conn, token):
    if not token:
        return None
    return conn.execute(
        """
        SELECT a.id, a.email, a.name, a.password_hash
        FROM auth.session s JOIN auth.account a ON a.id = s.account_id
        WHERE s.token_hash = %s AND s.expires_at > now()
        """,
        [_token_hash(token)],
    ).fetchone()


def logout(conn, token):
    if token:
        conn.execute("DELETE FROM auth.session WHERE token_hash = %s", [_token_hash(token)])
