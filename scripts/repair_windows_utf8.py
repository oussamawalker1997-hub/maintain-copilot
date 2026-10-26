"""Repair only original synthetic fixture imports, after a verified SQLite backup.

Run from the repository root, with the server stopped. Never re-decodes arbitrary data.
This file also works with the original v0.1 source distribution.
"""

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path


def is_known_encoding_variant(actual, expected):
    if actual == expected:
        return True
    try:
        return actual == expected.encode("utf-8").decode("cp1252")
    except UnicodeDecodeError:
        return False


def repair(root):
    root = Path(root)
    database = root / ".local/maintain.sqlite"
    fixtures = root / "fixtures/synthetic"
    if not (root / "pyproject.toml").is_file() or not database.is_file():
        raise RuntimeError("Run from the initialized maintain-copilot project directory")
    manifest = json.loads((fixtures / "documents.json").read_text(encoding="utf-8"))
    patches = []
    for name in (
        "src/maintain/cli.py",
        "src/maintain/db.py",
        "scripts/evaluate.py",
        "scripts/verify_live.py",
        "tests/conftest.py",
        "tests/test_tickets_operations.py",
    ):
        path = root / name
        if not path.is_file():
            continue
        before = path.read_text(encoding="utf-8")
        after = before.replace(".read_text()", '.read_text(encoding="utf-8")')
        if after != before:
            patches.append((path, before, after))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    backup_dir = root / ".local/encoding-backups" / stamp
    backup_dir.mkdir(parents=True)
    backup_path = backup_dir / "maintain.sqlite"
    db = sqlite3.connect(database)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        with sqlite3.connect(backup_path) as saved:
            db.backup(saved)
            if saved.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed; no repair performed")
        backup_path.chmod(0o600)
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        changes = []
        for item in manifest:
            rows = db.execute(
                """SELECT * FROM documents WHERE site=? AND family=? AND revision=?
                AND model=? AND hardware=? AND firmware_min=? AND firmware_max=?""",
                tuple(
                    item[k]
                    for k in (
                        "site",
                        "family",
                        "revision",
                        "model",
                        "hardware",
                        "firmware_min",
                        "firmware_max",
                    )
                ),
            ).fetchall()
            if len(rows) != 1:
                raise RuntimeError("Fixture identity is missing/ambiguous; no repair performed")
            doc = rows[0]
            if not is_known_encoding_variant(doc["title"], item["title"]):
                raise RuntimeError("Custom document title detected; no repair performed")
            # Match Pydantic's str_strip_whitespace normalization in DocumentRequest.
            pages = [
                page.strip()
                for page in (fixtures / item["file"])
                .read_text(encoding="utf-8")
                .split("\n---PAGE---\n")
            ]
            actual_pages = db.execute(
                "SELECT number,text FROM pages WHERE document_id=? ORDER BY number", (doc["id"],)
            ).fetchall()
            if len(actual_pages) != len(pages):
                raise RuntimeError("Custom page structure detected; no repair performed")
            for number, (actual, expected) in enumerate(zip(actual_pages, pages, strict=True), 1):
                if actual["number"] != number or not is_known_encoding_variant(
                    actual["text"], expected
                ):
                    raise RuntimeError("Custom page content detected; no repair performed")
            content_hash = hashlib.sha256(
                json.dumps(pages, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            if (
                doc["title"] != item["title"]
                or doc["content_hash"] != content_hash
                or any(a["text"] != e for a, e in zip(actual_pages, pages, strict=True))
            ):
                changes.append((doc["id"], item["title"], pages, content_hash))
        # Validate all fixtures before changing any document. Preserve IDs, status and credentials.
        for document_id, title, pages, content_hash in changes:
            db.execute("DELETE FROM pages WHERE document_id=?", (document_id,))
            for number, text in enumerate(pages, 1):
                db.execute(
                    "INSERT INTO pages(document_id,number,text) VALUES(?,?,?)",
                    (document_id, number, text),
                )
            db.execute(
                "UPDATE documents SET title=?,content_hash=? WHERE id=?",
                (title, content_hash, document_id),
            )
            db.execute(
                "INSERT INTO audit(actor,event,object_id,created_at) VALUES(?,?,?,?)",
                (
                    "encoding-migration",
                    "fixture.utf8_repaired",
                    document_id,
                    datetime.now(UTC).isoformat(),
                ),
            )
        # Runs are historical snapshots: preserve them unchanged. Re-run searches after repair.
        for path, before, _ in patches:
            destination = backup_dir / "source" / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(before, encoding="utf-8")
        for path, _, after in patches:
            path.write_text(after, encoding="utf-8")
        db.commit()
        print("UTF8_REPAIR_OK")
        print(f"Documents repaired: {len(changes)}")
        print(f"Source files updated: {len(patches)}")
        print(f"Verified backup: {backup_path}")
        print("Credentials, document IDs and existing tickets preserved. Run new searches.")
        return len(changes)
    except Exception:
        db.rollback()
        # Restore only source files whose original bytes were captured by this run.
        for path, before, _ in patches:
            if (backup_dir / "source" / path.relative_to(root)).is_file():
                path.write_text(before, encoding="utf-8")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    repair(Path.cwd())
