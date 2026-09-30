"""Database access. One Postgres user per job, so the raw layer is protected
by the database itself:

    admin     owner; creates schemas, users and grants (`thz init-db`)
    importer  read/write raw, nothing in analysed
    analysis  read-only raw, read/write analysed
    web       read-only raw and analysed
    auth      accounts and sessions only
"""
import os
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

SCHEMA = Path(__file__).with_name("schema.sql")

ROLES = ("importer", "analysis", "web", "auth")

GRANTS = """
REVOKE ALL ON SCHEMA raw, analysed, auth FROM {all};
REVOKE ALL ON ALL TABLES IN SCHEMA raw, analysed, auth FROM {all};
REVOKE ALL ON ALL SEQUENCES IN SCHEMA raw, analysed, auth FROM {all};

GRANT USAGE ON SCHEMA raw TO thz_importer, thz_analysis, thz_web;
GRANT USAGE ON SCHEMA analysed TO thz_analysis, thz_web;
GRANT USAGE ON SCHEMA auth TO thz_auth;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA raw TO thz_importer;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA raw TO thz_importer;

GRANT SELECT ON ALL TABLES IN SCHEMA raw TO thz_analysis;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA analysed TO thz_analysis;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA analysed TO thz_analysis;

GRANT SELECT ON ALL TABLES IN SCHEMA raw, analysed TO thz_web;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA auth TO thz_auth;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA auth TO thz_auth;
""".format(all=", ".join(f"thz_{r}" for r in ROLES))


def connect(role):
    var = f"DATABASE_URL_{role.upper()}"
    if var not in os.environ:
        raise SystemExit(f"{var} is not set: this container is not allowed to act as '{role}'")
    return psycopg.connect(os.environ[var], row_factory=dict_row)


def init(conn):
    """Create schemas, users and grants. Idempotent; needs the admin connection."""
    conn.execute(SCHEMA.read_text())
    for role in ROLES:
        name = sql.Identifier(f"thz_{role}")
        password = sql.Literal(os.environ[f"{role.upper()}_PASSWORD"])
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [f"thz_{role}"]).fetchone()
        verb = sql.SQL("ALTER" if exists else "CREATE")
        conn.execute(sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(verb, name, password))
    conn.execute(GRANTS)
    conn.commit()
