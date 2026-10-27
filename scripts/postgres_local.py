"""Local PostgreSQL foundation; does not switch the SQLite API or import its data.

Uses the official container's psql client. No host PostgreSQL/Python driver required.
"""

import argparse
import hashlib
import os
import re
import secrets
import subprocess
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ROLE_CONFIG = {
    "admin": ("maintain_admin", "admin_password"),
    "site_a": ("maintain_site_a", "site_a_password"),
    "site_b": ("maintain_site_b", "site_b_password"),
}
SECRET_FILES = ("admin-password", "site-a-password", "site-b-password")


def prepare(root=ROOT):
    directory = root / ".local/postgres"
    if directory.exists():
        if not all((directory / name).is_file() for name in SECRET_FILES):
            raise RuntimeError("Partial credential directory; stop and review it, do not overwrite")
        for name in SECRET_FILES:
            if not re.fullmatch(
                r"[a-f0-9]{64}", (directory / name).read_text(encoding="ascii").strip()
            ):
                raise RuntimeError("Unexpected credential format; no changes made")
        print("POSTGRES_SECRETS_ALREADY_PRESENT (unchanged)")
        return
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(mode=0o700)
    # Files must be readable by the container's postgres UID. The host parent is private.
    # POSIX bits do not assert Windows ACL protection; use a private user directory there.
    directory.chmod(0o700)
    for name in SECRET_FILES:
        fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(secrets.token_hex(32) + "\n")
    print("POSTGRES_SECRETS_READY (.local/postgres; values not displayed)")


def psql(statement, role="admin", *, allow_failure=False):
    user, secret = ROLE_CONFIG[role]
    # Shell text is constant except for identifiers drawn from this fixed allowlist.
    shell = (
        f'export PGPASSWORD="$(cat /run/secrets/{secret})"; '
        "export PGCLIENTENCODING=UTF8; "
        f"exec psql -X -qAt -h 127.0.0.1 -U {user} -d maintain "
        "-v ON_ERROR_STOP=1 -P pager=off"
    )
    command = [
        "docker",
        "compose",
        "-f",
        str(ROOT / "compose.postgres.yaml"),
        "exec",
        "-T",
        "postgres",
        "sh",
        "-c",
        shell,
    ]
    result = subprocess.run(
        command, input=statement, encoding="utf-8", capture_output=True, timeout=60, cwd=ROOT
    )
    if result.returncode and not allow_failure:
        raise RuntimeError("PostgreSQL command failed: " + result.stderr.strip()[-1500:])
    return result


def migration_script(path):
    if not re.fullmatch(r"\d{3}_[a-z_]+\.sql", path.name):
        raise RuntimeError("Invalid migration filename")
    content = path.read_text(encoding="utf-8")
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    name = path.stem
    return f"""BEGIN;
SELECT pg_advisory_xact_lock(714203001);
SET LOCAL ROLE maintain_owner;
CREATE TABLE IF NOT EXISTS maintain.schema_migrations (
  version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now()
);
DO $check$ BEGIN
  IF EXISTS (SELECT 1 FROM maintain.schema_migrations
             WHERE version = '{name}' AND checksum <> '{checksum}') THEN
    RAISE EXCEPTION 'Applied migration checksum mismatch; add a new migration instead';
  END IF;
END $check$;
SELECT NOT EXISTS (SELECT 1 FROM maintain.schema_migrations WHERE version = '{name}')
  AS apply_migration \\gset
\\if :apply_migration
{content}
INSERT INTO maintain.schema_migrations(version, checksum) VALUES ('{name}', '{checksum}');
\\endif
COMMIT;
"""


def migrate():
    files = sorted((ROOT / "migrations/postgres").glob("*.sql"))
    if not files:
        raise RuntimeError("No migrations found")
    for path in files:
        psql(migration_script(path))
        print("MIGRATION_OK " + path.stem)
    print("POSTGRES_MIGRATIONS_OK")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def scalar(statement, role="admin"):
    return psql(statement, role).stdout.strip()


def expect_denied(statement, role, label):
    result = psql(statement, role, allow_failure=True)
    # A failed connection must not be mistaken for successful authorization enforcement.
    require(
        result.returncode != 0 and "42501" in result.stderr,
        label + ": expected an insufficient-privilege error",
    )
    print("PASS " + label)


def verify():
    require(
        scalar("SELECT current_setting('server_version_num')::int / 10000;") == "17",
        "Expected PostgreSQL major 17",
    )
    require(
        scalar("SELECT current_setting('server_encoding');") == "UTF8",
        "Database encoding must be UTF8",
    )
    require(
        scalar("SELECT count(*) FROM maintain.schema_migrations;") == "1",
        "Unexpected migration state",
    )
    original = (ROOT / "migrations/postgres/001_core.sql").read_text(encoding="utf-8")
    with TemporaryDirectory() as directory:
        changed = Path(directory) / "001_core.sql"
        changed.write_text(original + "\n-- intentional checksum verification\n", encoding="utf-8")
        rejected = psql(migration_script(changed), allow_failure=True)
        require(
            rejected.returncode != 0 and "Applied migration checksum mismatch" in rejected.stderr,
            "Changed migration was not rejected",
        )
    require(
        scalar("SELECT checksum FROM maintain.schema_migrations WHERE version='001_core';")
        == hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "Migration checksum changed after rejected modification",
    )
    print("PASS modified_migration_rejected")
    for role, site in (("site_a", "DE-A"), ("site_b", "DE-B")):
        require(scalar("SELECT maintain.current_site();", role) == site, "Wrong role/site mapping")
        require(
            scalar(
                """SELECT NOT rolsuper AND NOT rolbypassrls AND NOT rolcreatedb
                AND NOT rolcreaterole FROM pg_roles WHERE rolname = current_user;""",
                role,
            )
            == "t",
            "Runtime role has elevated privileges",
        )
    require(
        scalar("""SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='maintain' AND c.relkind='r' AND c.relname <> 'schema_migrations'
        AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity
             OR pg_has_role('maintain_site_a', c.relowner, 'MEMBER')
             OR pg_has_role('maintain_site_b', c.relowner, 'MEMBER'));""")
        == "0",
        "RLS/ownership invariant failed",
    )
    print("PASS role_privileges_and_forced_rls")
    tag = "verify-" + uuid.uuid4().hex  # Generated identifier only; never SQL input from a user.
    doc = tag + "-doc"
    try:
        psql(f"""BEGIN;
INSERT INTO maintain.sites(site) VALUES ('DE-A'),('DE-B') ON CONFLICT DO NOTHING;
INSERT INTO maintain.assets(site,id,model,hardware,firmware) VALUES
 ('DE-A','{tag}','verification','rev-B','2.4'),
 ('DE-B','{tag}','verification','rev-B','2.4');
INSERT INTO maintain.documents(site,id,title,family,revision,model,hardware,
 firmware_min,firmware_max,content_hash,status) VALUES
 ('DE-B','{doc}','UTF8 R\u00fcckmeldung','verify','1','verification','rev-B',
  '2.0','2.9','{doc}','published');
INSERT INTO maintain.pages(site,document_id,number,text)
 VALUES('DE-B','{doc}',1,'E042 R\u00fcckmeldung mat\u00e9rielle');
COMMIT;""")
        for role, own_site in (("site_a", "DE-A"), ("site_b", "DE-B")):
            require(
                scalar(f"SELECT site FROM maintain.assets WHERE id='{tag}';", role) == own_site,
                "Cross-site asset visibility",
            )
            require(
                scalar(
                    f"""BEGIN;
INSERT INTO maintain.assets(site,id,model,hardware,firmware)
  VALUES('{own_site}','{tag}-own','verification','rev-B','2.4');
UPDATE maintain.assets SET firmware='2.5' WHERE id='{tag}-own';
SELECT firmware FROM maintain.assets WHERE id='{tag}-own';
WITH changed AS (DELETE FROM maintain.assets WHERE id='{tag}-own' RETURNING id)
  SELECT count(*) FROM changed;
ROLLBACK;""",
                    role,
                )
                == "2.5\n1",
                "Own-site write lifecycle failed",
            )
        print("PASS reads_are_site_scoped")
        print("PASS own_site_insert_update_delete")
        require(
            scalar(
                f"""SELECT count(*) FROM maintain.assets
            WHERE site='DE-B' AND id='{tag}';""",
                "site_a",
            )
            == "0",
            "Forged site filter leaked data",
        )
        require(
            scalar(
                f"""SELECT count(*) FROM maintain.documents d
            JOIN maintain.pages p ON (p.site,p.document_id)=(d.site,d.id)
            WHERE d.id='{doc}';""",
                "site_a",
            )
            == "0",
            "Cross-site join leaked data",
        )
        require(
            scalar(
                f"""SELECT count(*) FROM maintain.pages
            WHERE document_id='{doc}' AND search_vector @@ plainto_tsquery('simple','E042');""",
                "site_a",
            )
            == "0",
            "Full-text search leaked site B",
        )
        require(
            scalar(f"SELECT text FROM maintain.pages WHERE document_id='{doc}';", "site_b")
            == "E042 R\u00fcckmeldung mat\u00e9rielle",
            "UTF8 round trip failed",
        )
        print("PASS joins_search_and_utf8")
        require(
            scalar(
                f"""WITH changed AS (
            UPDATE maintain.assets SET model='unauthorized' WHERE site='DE-B' AND id='{tag}'
            RETURNING id) SELECT count(*) FROM changed;""",
                "site_a",
            )
            == "0",
            "Cross-site update succeeded",
        )
        require(
            scalar(
                f"""WITH changed AS (
            DELETE FROM maintain.assets WHERE site='DE-B' AND id='{tag}' RETURNING id
            ) SELECT count(*) FROM changed;""",
                "site_a",
            )
            == "0",
            "Cross-site delete succeeded",
        )
        print("PASS cross_site_update_delete_blocked")
        verbose = "\\set VERBOSITY verbose\n"
        expect_denied(
            verbose
            + f"""INSERT INTO maintain.assets(site,id,model,hardware,firmware)
            VALUES('DE-B','{tag}-forged','x','x','1');""",
            "site_a",
            "cross_site_insert_denied",
        )
        foreign_key = psql(
            verbose
            + f"""INSERT INTO maintain.pages(site,document_id,number,text)
            VALUES('DE-A','{doc}',1,'cross-site reference must fail');""",
            "site_a",
            allow_failure=True,
        )
        require(
            foreign_key.returncode != 0 and "23503" in foreign_key.stderr,
            "Cross-site document relationship was not rejected",
        )
        print("PASS composite_foreign_key_blocks_cross_site_reference")
        expect_denied(verbose + "TRUNCATE maintain.assets;", "site_a", "truncate_denied")
        expect_denied(verbose + "SET ROLE maintain_site_b;", "site_a", "role_impersonation_denied")
        expect_denied(
            verbose + "ALTER TABLE maintain.assets DISABLE ROW LEVEL SECURITY;",
            "site_a",
            "rls_disable_denied",
        )
        expect_denied(
            verbose + "UPDATE maintain.audit SET event='forged';", "site_a", "audit_update_denied"
        )
        require(
            scalar(
                f"""BEGIN; SET ROLE maintain_runtime;
            SELECT count(*) FROM maintain.assets WHERE id='{tag}'; ROLLBACK;""",
                "site_a",
            )
            == "0",
            "Unmapped role must fail closed",
        )
        print("PASS unmapped_role_fails_closed")
    finally:
        psql(f"""BEGIN;
DELETE FROM maintain.pages WHERE document_id='{doc}';
DELETE FROM maintain.documents WHERE id='{doc}';
DELETE FROM maintain.assets WHERE id IN ('{tag}','{tag}-forged');
COMMIT;""")
    print("POSTGRES_FOUNDATION_OK (API still uses SQLite)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "migrate", "verify"))
    args = parser.parse_args()
    try:
        {"prepare": prepare, "migrate": migrate, "verify": verify}[args.command]()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
