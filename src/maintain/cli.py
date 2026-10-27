import argparse
import json
import logging
import os
import secrets
import sqlite3
from dataclasses import replace
from pathlib import Path

import psycopg
import uvicorn

from maintain.config import Settings
from maintain.db import connect, digest, initialize
from maintain.documents import ingest
from maintain.models import DocumentRequest
from maintain.tickets import dispatch


def seed(database: Path, fixture_dir: Path):
    target = database.parent / "demo-credentials.json"
    if target.exists():
        raise SystemExit("Credential file already exists; refusing to overwrite local keys")
    initialize(database)
    credentials = {}
    with connect(database) as db:
        if db.execute("SELECT count(*) FROM principals").fetchone()[0]:
            raise SystemExit(
                "Database already initialized; refusing to overwrite data or credentials"
            )
        for user, site, role in (
            ("tech-a", "DE-A", "technician"),
            ("editor-a", "DE-A", "editor"),
            ("tech-b", "DE-B", "technician"),
        ):
            token = secrets.token_urlsafe(32)
            credentials[user] = token
            db.execute(
                "INSERT INTO principals(id,token_hash,site,role) VALUES(?,?,?,?)",
                (user, digest(token), site, role),
            )
        for asset in json.loads((fixture_dir / "assets.json").read_text(encoding="utf-8")):
            db.execute("INSERT INTO assets VALUES(:id,:site,:model,:hardware,:firmware)", asset)
        for item in json.loads((fixture_dir / "documents.json").read_text(encoding="utf-8")):
            text = (fixture_dir / item.pop("file")).read_text(encoding="utf-8")
            status = item.pop("status")
            site = item.pop("site")
            result = ingest(
                db,
                {"id": "fixture-seeder", "site": site},
                DocumentRequest(**item, pages=text.split("\n---PAGE---\n")),
            )
            if result["status"] != "quarantined":
                db.execute("UPDATE documents SET status=? WHERE id=?", (status, result["id"]))
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(credentials, f, indent=2)
        f.write("\n")
    print(f"Initialized synthetic demonstration. Local keys: {target}")
    print("Keep this file private. Keys are never embedded in the interface or tracked by Git.")


def backup(database: Path, output: Path):
    if output.exists():
        raise SystemExit("Backup destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    with connect(database) as db, sqlite3.connect(output) as destination:
        db.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("Backup integrity check failed")
    output.chmod(0o600)
    print(f"Backup created: {output}")


def main():
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(prog="maintain")
    parser.add_argument("--database", type=Path, default=settings.database)
    commands = parser.add_subparsers(dest="command", required=True)
    seed_cmd = commands.add_parser("seed")
    seed_cmd.add_argument("--fixtures", type=Path, default=Path("fixtures/synthetic"))
    pg_seed = commands.add_parser("seed-postgres")
    pg_seed.add_argument("--fixtures", type=Path, default=Path("fixtures/synthetic"))
    serve_cmd = commands.add_parser("serve")
    serve_cmd.add_argument("--port", type=int, default=8000)
    commands.add_parser("dispatch")
    backup_cmd = commands.add_parser("backup")
    backup_cmd.add_argument("output", type=Path)
    args = parser.parse_args()
    settings = replace(settings, database=args.database)
    if args.command == "seed-postgres":
        from maintain.postgres_seed import seed_postgres

        if settings.backend != "postgres":
            raise SystemExit("Set MAINTAIN_BACKEND=postgres explicitly before provisioning")
        try:
            seed_postgres(settings, args.fixtures)
        except psycopg.Error:
            raise SystemExit(
                "PostgreSQL provisioning failed; details withheld to protect data"
            ) from None
        except (RuntimeError, OSError, ValueError) as exc:
            raise SystemExit(str(exc)) from None
    elif args.command == "seed":
        if settings.backend != "sqlite":
            raise SystemExit("Use seed-postgres for PostgreSQL; SQLite data left unchanged")
        seed(args.database, args.fixtures)
    elif args.command == "serve":
        from maintain.app import create_app

        logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
        # Local demonstration only. An enterprise deployment requires a different security model.
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, access_log=False)
    elif args.command == "dispatch":
        if settings.backend == "postgres":
            from maintain.postgres import SITE_ROLES, site_connection

            total = 0
            for site in SITE_ROLES:
                with site_connection(settings, site) as db:
                    total += dispatch(db)
            print(f"Simulated deliveries: {total}")
        else:
            with connect(args.database) as db:
                print(f"Simulated deliveries: {dispatch(db)}")
    elif args.command == "backup":
        if settings.backend != "sqlite":
            raise SystemExit("This backup command supports SQLite only; no backup created")
        backup(args.database, args.output)


if __name__ == "__main__":
    main()
