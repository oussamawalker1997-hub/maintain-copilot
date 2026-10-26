import hashlib
import json
import shutil
from pathlib import Path

import pytest
from conftest import FIXTURES

from maintain.cli import seed
from maintain.db import connect
from scripts.repair_windows_utf8 import repair


def make_project(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "fixtures/synthetic")
    (tmp_path / "pyproject.toml").write_text("# Test project\n", encoding="utf-8")
    database = tmp_path / ".local/maintain.sqlite"
    seed(database, tmp_path / "fixtures/synthetic")
    return database


def test_seed_uses_utf8_even_if_default_reader_is_cp1252(tmp_path, monkeypatch):
    original = Path.read_text

    def legacy_read(path, encoding=None, errors=None):
        return original(path, encoding=encoding or "cp1252", errors=errors)

    monkeypatch.setattr(Path, "read_text", legacy_read)
    database = make_project(tmp_path)
    with connect(database) as db:
        text = db.execute(
            """SELECT p.text FROM pages p JOIN documents d ON d.id=p.document_id
            WHERE d.site='DE-A' AND d.family='C2-MAN' AND d.revision='3' AND p.number=2"""
        ).fetchone()[0]
        assert "R\u00fcckmeldung" in text
        assert "mat\u00e9rielle" in text
        assert "R\u00c3\u00bcckmeldung" not in text


def test_repair_preserves_keys_ids_and_rebuilds_fts(tmp_path):
    database = make_project(tmp_path)
    key_file = database.parent / "demo-credentials.json"
    original_keys = key_file.read_bytes()
    with connect(database) as db:
        original_ids = [r[0] for r in db.execute("SELECT id FROM documents ORDER BY id")]
        for doc in db.execute("SELECT id,title FROM documents").fetchall():
            pages = [
                r[0].encode("utf-8").decode("cp1252")
                for r in db.execute(
                    "SELECT text FROM pages WHERE document_id=? ORDER BY number", (doc["id"],)
                )
            ]
            db.execute("DELETE FROM pages WHERE document_id=?", (doc["id"],))
            for number, text in enumerate(pages, 1):
                db.execute(
                    "INSERT INTO pages(document_id,number,text) VALUES(?,?,?)",
                    (doc["id"], number, text),
                )
            wrong_hash = hashlib.sha256(json.dumps(pages, ensure_ascii=False).encode()).hexdigest()
            db.execute(
                "UPDATE documents SET title=?,content_hash=? WHERE id=?",
                (
                    doc["title"].encode("utf-8").decode("cp1252"),
                    wrong_hash,
                    doc["id"],
                ),
            )
    assert repair(tmp_path) > 0
    assert key_file.read_bytes() == original_keys
    with connect(database) as db:
        assert [r[0] for r in db.execute("SELECT id FROM documents ORDER BY id")] == original_ids
        hits = db.execute(
            "SELECT text FROM page_fts WHERE page_fts MATCH ?", ('"R\u00fcckmeldung"',)
        ).fetchall()
        assert any("R\u00fcckmeldung" in row[0] for row in hits)
    assert len(list(database.parent.glob("encoding-backups/*/maintain.sqlite"))) == 1
    assert repair(tmp_path) == 0


def test_repair_refuses_custom_content_without_modifying_it(tmp_path):
    database = make_project(tmp_path)
    with connect(database) as db:
        row = db.execute("SELECT id FROM pages LIMIT 1").fetchone()
        db.execute(
            "UPDATE pages SET text='Custom content must not be overwritten' WHERE id=?", (row[0],)
        )
    with pytest.raises(RuntimeError, match="Custom page content"):
        repair(tmp_path)
    with connect(database) as db:
        assert db.execute("SELECT text FROM pages WHERE id=?", (row[0],)).fetchone()[0] == (
            "Custom content must not be overwritten"
        )
