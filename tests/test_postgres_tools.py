import hashlib

import pytest

from scripts.postgres_local import SECRET_FILES, migration_script, prepare


def test_postgres_secrets_are_unique_private_and_not_printed(tmp_path, capsys):
    prepare(tmp_path)
    directory = tmp_path / ".local/postgres"
    values = [(directory / name).read_text(encoding="ascii").strip() for name in SECRET_FILES]
    assert len(set(values)) == 3
    assert all(len(value) == 64 for value in values)
    assert all(
        (directory / name).read_bytes() == value.encode("ascii") + b"\n"
        for name, value in zip(SECRET_FILES, values, strict=True)
    )
    output = capsys.readouterr().out
    assert "POSTGRES_SECRETS_READY" in output
    assert all(value not in output for value in values)
    import os

    if os.name == "posix":
        assert directory.stat().st_mode & 0o077 == 0


def test_preparing_twice_preserves_postgres_credentials(tmp_path):
    prepare(tmp_path)
    directory = tmp_path / ".local/postgres"
    before = [(directory / name).read_bytes() for name in SECRET_FILES]
    prepare(tmp_path)
    assert [(directory / name).read_bytes() for name in SECRET_FILES] == before


def test_partial_credentials_are_not_overwritten(tmp_path):
    directory = tmp_path / ".local/postgres"
    directory.mkdir(parents=True)
    (directory / SECRET_FILES[0]).write_text("existing", encoding="ascii")
    with pytest.raises(RuntimeError, match="Partial credential"):
        prepare(tmp_path)
    assert (directory / SECRET_FILES[0]).read_text(encoding="ascii") == "existing"


def test_migrations_are_checked_and_newlines_are_canonical(tmp_path):
    path = tmp_path / "001_test.sql"
    path.write_bytes(b"SELECT 1;\r\n")
    script = migration_script(path)
    checksum = hashlib.sha256(b"SELECT 1;\n").hexdigest()
    assert checksum in script
    assert "pg_advisory_xact_lock" in script
    assert script.startswith("BEGIN;")
    assert script.rstrip().endswith("COMMIT;")
    invalid = tmp_path / "001_unsafe'name.sql"
    with pytest.raises(RuntimeError, match="Invalid migration filename"):
        migration_script(invalid)


@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
def test_repair_preserves_secret_files_and_checks_all_authentications(
    tmp_path, monkeypatch, capsys, ending
):
    from types import SimpleNamespace

    from scripts import postgres_local as pg

    directory = tmp_path / ".local/postgres"
    directory.mkdir(parents=True)
    for name in SECRET_FILES:
        (directory / name).write_bytes(b"a" * 64 + ending)
    before = [(directory / name).read_bytes() for name in SECRET_FILES]
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    checked = []

    def scalar(sql, role):
        checked.append(role)
        return pg.ROLE_CONFIG[role][0]

    monkeypatch.setattr(pg, "ROOT", tmp_path)
    monkeypatch.setattr(pg.subprocess, "run", run)
    monkeypatch.setattr(pg, "scalar", scalar)
    pg.repair_passwords()
    assert checked == ["admin", "site_a", "site_b"]
    assert [(directory / name).read_bytes() for name in SECRET_FILES] == before
    assert "a" * 64 not in str(calls)
    assert "a" * 64 not in capsys.readouterr().out
    assert calls[0][1]["input"].startswith("BEGIN;")
    assert calls[0][1]["input"].endswith("COMMIT;\n")


def test_repair_rejects_invalid_secret_before_database_access(tmp_path, monkeypatch):
    from scripts import postgres_local as pg

    directory = tmp_path / ".local/postgres"
    directory.mkdir(parents=True)
    (directory / SECRET_FILES[0]).write_bytes(b"invalid")
    monkeypatch.setattr(pg, "ROOT", tmp_path)
    monkeypatch.setattr(pg.subprocess, "run", lambda *a, **kw: pytest.fail("database accessed"))
    with pytest.raises(RuntimeError, match="Unexpected credential format"):
        pg.repair_passwords()
