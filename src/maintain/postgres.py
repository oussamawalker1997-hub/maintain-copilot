"""Local two-site PostgreSQL runtime. No superuser credentials or role switching."""

import re
from contextlib import ExitStack, contextmanager

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from maintain.db import digest
from maintain.storage import Repository

SITE_ROLES = {
    "DE-A": ("maintain_site_a", "site-a-password"),
    "DE-B": ("maintain_site_b", "site-b-password"),
}


def password(path):
    data = path.read_bytes()
    if not re.fullmatch(rb"[a-f0-9]{64}(?:\r?\n)?", data):
        raise ValueError("Invalid local PostgreSQL credential format")
    return data.rstrip(b"\r\n").decode("ascii")


@contextmanager
def site_connection(settings, site):
    user, filename = SITE_ROLES[site]
    with psycopg.connect(
        host="127.0.0.1",
        port=settings.postgres_port,
        dbname="maintain",
        user=user,
        password=password(settings.postgres_secrets / filename),
        connect_timeout=5,
        row_factory=dict_row,
        options=(
            "-c search_path=maintain,pg_catalog -c statement_timeout=10000 -c lock_timeout=5000"
        ),
    ) as connection:
        yield Repository(connection, site)


def check_database(settings):
    for site, (user, _) in SITE_ROLES.items():
        with site_connection(settings, site) as db:
            row = db.query("""SELECT current_user AS name, maintain.current_site() AS site,
                rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,
                pg_has_role(current_user, 'maintain_owner', 'MEMBER') AS owner_member
                FROM pg_roles
                WHERE rolname=current_user""").fetchone()
            if (
                row["name"] != user
                or row["site"] != site
                or any(
                    row[k]
                    for k in (
                        "rolsuper",
                        "rolbypassrls",
                        "rolcreatedb",
                        "rolcreaterole",
                        "owner_member",
                    )
                )
            ):
                raise RuntimeError("Unsafe PostgreSQL runtime role")
            db.query("SELECT id FROM assets LIMIT 0")


@contextmanager
def authenticated_session(settings, authorization):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    token = authorization[7:]
    if not 20 <= len(token) <= 256:
        raise HTTPException(401, "Invalid token")
    # Two fixed development sites: resolve the token through both RLS-scoped roles.
    # Fail closed if absent, ambiguous, or if either database connection fails.
    with ExitStack() as stack:
        found = []
        for site in SITE_ROLES:
            db = stack.enter_context(site_connection(settings, site))
            row = db.query(
                "SELECT id FROM principals WHERE token_hash={p} AND active={p}",
                (digest(token), True),
            ).fetchone()
            if row:
                found.append(db)
        if len(found) != 1:
            raise HTTPException(401, "Invalid token")
        yield found[0]
