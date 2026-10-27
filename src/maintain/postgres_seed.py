"""Explicit administrator-only fixture provisioning for an empty local demo database."""

import json
import os
import secrets

import psycopg
from psycopg.rows import dict_row

from maintain.db import digest
from maintain.documents import ingest
from maintain.models import DocumentRequest
from maintain.postgres import password
from maintain.storage import Repository

BUSINESS_TABLES = (
    "principals",
    "assets",
    "documents",
    "pages",
    "runs",
    "tickets",
    "outbox",
    "simulated_work_orders",
    "feedback",
    "audit",
)


def seed_postgres(settings, fixtures):
    target = settings.postgres_secrets / "demo-credentials.json"
    if target.exists():
        raise RuntimeError("PostgreSQL demo credentials already exist; refusing to overwrite")
    created = False
    try:
        # Administrative connection is confined to this explicit provisioning command.
        with psycopg.connect(
            host="127.0.0.1",
            port=settings.postgres_port,
            dbname="maintain",
            user="maintain_admin",
            password=password(settings.postgres_secrets / "admin-password"),
            connect_timeout=5,
            row_factory=dict_row,
            options="-c search_path=maintain,pg_catalog -c lock_timeout=5000",
        ) as connection:
            stores = {site: Repository(connection, site) for site in ("DE-A", "DE-B")}
            for store in stores.values():
                store.write_lock()
            for table in BUSINESS_TABLES:
                if connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                    raise RuntimeError("PostgreSQL database is not empty; no fixtures inserted")
            if not connection.execute(
                "SELECT version FROM schema_migrations WHERE version='001_core'"
            ).fetchone():
                raise RuntimeError("Apply PostgreSQL migrations before provisioning")
            connection.execute("INSERT INTO sites VALUES ('DE-A'),('DE-B') ON CONFLICT DO NOTHING")
            credentials = {}
            for user, site, role in (
                ("tech-a", "DE-A", "technician"),
                ("editor-a", "DE-A", "editor"),
                ("tech-b", "DE-B", "technician"),
            ):
                token = secrets.token_urlsafe(32)
                credentials[user] = token
                stores[site].insert(
                    "principals", dict(id=user, token_hash=digest(token), role=role)
                )
            for asset in json.loads((fixtures / "assets.json").read_text(encoding="utf-8")):
                stores[asset["site"]].insert("assets", asset)
            for item in json.loads((fixtures / "documents.json").read_text(encoding="utf-8")):
                text = (fixtures / item.pop("file")).read_text(encoding="utf-8")
                status, site = item.pop("status"), item.pop("site")
                store = stores[site]
                result = ingest(
                    store,
                    {"id": "fixture-seeder", "site": site},
                    DocumentRequest(**item, pages=text.split("\n---PAGE---\n")),
                )
                if result["status"] != "quarantined":
                    store.query(
                        "UPDATE documents SET status={p} WHERE id={p} AND site={p}",
                        (status, result["id"], site),
                    )
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(fd, "wb") as stream:
                stream.write((json.dumps(credentials, indent=2) + "\n").encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException:
        if created:
            target.unlink()
        raise
    print(f"POSTGRES_DEMO_READY ({target}; values not displayed)")
