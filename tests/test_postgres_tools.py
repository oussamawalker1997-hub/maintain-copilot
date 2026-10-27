import hashlib

import pytest

from scripts.postgres_local import SECRET_FILES, migration_script, prepare


def test_postgres_secrets_are_unique_private_and_not_printed(tmp_path, capsys):
    prepare(tmp_path)
    directory = tmp_path / ".local/postgres"
    values = [(directory / name).read_text(encoding="ascii").strip() for name in SECRET_FILES]
    assert len(set(values)) == 3
    assert all(len(value) == 64 for value in values)
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
