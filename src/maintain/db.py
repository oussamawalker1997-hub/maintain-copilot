import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path


def now():
    return datetime.now(UTC).isoformat()


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


@contextmanager
def connect(path: Path):
    # FastAPI may enter/exit a sync dependency on different pool threads.
    # Every request owns its connection; no concurrent operations share it.
    db = sqlite3.connect(path, timeout=10, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(files("maintain").joinpath("schema.sql").read_text(encoding="utf-8"))
        if db.execute("SELECT version FROM schema_version").fetchone()[0] != 1:
            raise RuntimeError("Unsupported database schema; migration required")
    path.chmod(0o600)


def audit(db, actor, event, object_id):
    db.execute(
        "INSERT INTO audit(actor,event,object_id,created_at) VALUES(?,?,?,?)",
        (actor, event, object_id, now()),
    )
