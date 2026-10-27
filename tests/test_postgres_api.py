"""Real PostgreSQL API contract tests, enabled only in a disposable CI instance."""

import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest
import test_access_and_search as access
import test_documents as documents
import test_tickets_operations as operations
from conftest import FIXTURES, headers, question
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from maintain.app import create_app
from maintain.config import Settings
from maintain.postgres import password, site_connection
from maintain.postgres_seed import BUSINESS_TABLES, seed_postgres
from maintain.tickets import dispatch

pytestmark = pytest.mark.skipif(
    os.getenv("MAINTAIN_PG_TEST_DISPOSABLE") != "1",
    reason="Requires explicitly disposable PostgreSQL CI instance",
)


@contextmanager
def admin(settings):
    with psycopg.connect(
        host="127.0.0.1",
        port=settings.postgres_port,
        dbname="maintain",
        user="maintain_admin",
        password=password(settings.postgres_secrets / "admin-password"),
        row_factory=dict_row,
    ) as connection:
        yield connection


@pytest.fixture
def pg_setup(tmp_path):
    # Never point these destructive fixture resets at the developer's default port 15432.
    assert os.getenv("MAINTAIN_PG_PORT") == "25432", "Disposable test port must be 25432"
    source = Path(".local/postgres")
    secrets = tmp_path / "postgres"
    secrets.mkdir()
    for name in ("admin-password", "site-a-password", "site-b-password"):
        shutil.copyfile(source / name, secrets / name)
    settings = Settings(
        tmp_path / "must-not-create.sqlite",
        backend="postgres",
        postgres_secrets=secrets,
        postgres_port=25432,
        requests_per_minute=1000,
    )
    with admin(settings) as db:
        tables = ",".join("maintain." + name for name in BUSINESS_TABLES)
        db.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    seed_postgres(settings, FIXTURES)
    keys = json.loads((secrets / "demo-credentials.json").read_text(encoding="utf-8"))
    with TestClient(create_app(settings)) as client:
        yield client, settings, keys
    assert not settings.database.exists(), "PostgreSQL must never fall back to SQLite"


SCENARIOS = [
    access.test_no_token_and_invalid_token_are_rejected,
    access.test_scope_applies_to_assets_search_and_pages,
    access.test_versions_are_numeric_and_sources_applicable,
    access.test_unknown_codes_abstain_even_with_common_words,
    access.test_incomplete_variant_requires_clarification,
    access.test_fts_operators_are_treated_as_data,
    access.test_run_private_and_source_revocation_invalidates_history,
    access.test_parallel_site_searches_do_not_mix_context,
    documents.test_editor_required_for_ingestion,
    documents.test_draft_requires_explicit_publication_and_duplicate_is_idempotent,
    documents.test_duplicate_metadata_mismatch_does_not_override,
    documents.test_empty_and_image_only_documents_quarantined,
    documents.test_invalid_ranges_and_ambiguous_inputs_rejected,
    documents.test_partial_overlap_conflict_abstains,
    documents.test_exact_range_supersedes_previous_revision,
    operations.test_confirmation_and_run_asset_match_required,
    operations.test_invalid_payload_does_not_echo_sensitive_input,
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda fn: fn.__name__)
def test_shared_api_contract(pg_setup, scenario):
    scenario(pg_setup)


def test_pg_concurrent_tickets_and_workers_have_one_effect(pg_setup):
    client, settings, keys = pg_setup
    body = operations.ticket_payload(question(client, keys).json())
    auth = headers(keys) | {"Idempotency-Key": "pg-parallel-ticket"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(
            pool.map(lambda _: client.post("/v1/tickets", headers=auth, json=body), range(10))
        )
    assert all(r.status_code == 202 for r in responses)
    assert len({r.json()["id"] for r in responses}) == 1
    assert (
        client.post(
            "/v1/tickets", headers=auth, json=body | {"observations": "changed"}
        ).status_code
        == 409
    )

    def deliver(_):
        with site_connection(settings, "DE-A") as db:
            return dispatch(db)

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(deliver, range(4))) == 1
    with site_connection(settings, "DE-A") as db:
        assert db.query("SELECT count(*) AS n FROM simulated_work_orders").fetchone()["n"] == 1
    ticket = responses[0].json()["id"]
    assert client.get(f"/v1/tickets/{ticket}", headers=headers(keys)).json()["status"] == "sent"
    assert client.get(f"/v1/tickets/{ticket}", headers=headers(keys, "tech-b")).status_code == 404


def test_pg_revoked_source_blocks_delivery(pg_setup):
    client, settings, keys = pg_setup
    result = question(client, keys).json()
    response = client.post(
        "/v1/tickets",
        headers=headers(keys) | {"Idempotency-Key": "pg-revoke"},
        json=operations.ticket_payload(result),
    )
    assert response.status_code == 202
    doc = result["sources"][0]["document_id"]
    assert (
        client.post(f"/v1/documents/{doc}/revoke", headers=headers(keys, "editor-a")).status_code
        == 200
    )
    with site_connection(settings, "DE-A") as db:
        assert dispatch(db) == 0
        assert (
            db.query(
                "SELECT status FROM tickets WHERE id={p}", (response.json()["id"],)
            ).fetchone()["status"]
            == "blocked"
        )


def test_pg_revoked_and_ambiguous_credentials_fail_closed(pg_setup):
    client, settings, keys = pg_setup
    with admin(settings) as db:
        db.execute("UPDATE maintain.principals SET active=false WHERE site='DE-A' AND id='tech-a'")
    assert question(client, keys).status_code == 401
    with admin(settings) as db:
        db.execute("UPDATE maintain.principals SET active=true WHERE site='DE-A'")
        db.execute("""UPDATE maintain.principals SET token_hash=(SELECT token_hash
                   FROM maintain.principals WHERE site='DE-A' AND id='tech-a') WHERE site='DE-B'""")
    assert question(client, keys).status_code == 401


def test_pg_failure_rolls_back_run_and_audit_without_exposing_error(pg_setup):
    client, settings, keys = pg_setup
    with admin(settings) as db:
        db.execute("""CREATE FUNCTION maintain.test_reject_audit() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'PRIVATE_DATABASE_SENTINEL'; END $$""")
        db.execute("""CREATE TRIGGER test_reject_audit BEFORE INSERT ON maintain.audit
        FOR EACH ROW EXECUTE FUNCTION maintain.test_reject_audit()""")
    try:
        response = question(client, keys)
        assert response.status_code == 500
        assert "PRIVATE_DATABASE_SENTINEL" not in response.text
        with admin(settings) as db:
            assert db.execute("SELECT count(*) AS n FROM maintain.runs").fetchone()["n"] == 0
    finally:
        with admin(settings) as db:
            db.execute("DROP TRIGGER test_reject_audit ON maintain.audit")
            db.execute("DROP FUNCTION maintain.test_reject_audit()")


def test_pg_backend_failure_never_falls_back_to_sqlite(pg_setup, monkeypatch):
    import maintain.postgres as pg

    client, _, keys = pg_setup

    @contextmanager
    def unavailable(*args, **kwargs):
        raise psycopg.OperationalError("PRIVATE_DATABASE_SENTINEL")
        yield

    monkeypatch.setattr(pg, "site_connection", unavailable)
    response = question(client, keys)
    assert response.status_code == 503
    assert "PRIVATE_DATABASE_SENTINEL" not in response.text


def test_pg_same_principal_id_on_two_sites_is_safe(pg_setup):
    client, settings, keys = pg_setup
    with admin(settings) as db:
        db.execute("UPDATE maintain.principals SET id='tech-a' WHERE site='DE-B'")
    a = question(client, keys).json()
    b = client.post(
        "/v1/answers",
        headers=headers(keys, "tech-b"),
        json={"asset_id": "NW-B01", "question": "E042"},
    ).json()
    assert a["status"] == b["status"] == "evidence_found"
    assert "B_PRIVATE" not in json.dumps(a)
    assert "B_PRIVATE" in json.dumps(b)
    assert client.get(f"/v1/runs/{a['run_id']}", headers=headers(keys, "tech-b")).status_code == 404
    with TestClient(create_app(replace(settings, requests_per_minute=1))) as limited:
        assert limited.get("/v1/me", headers=headers(keys)).status_code == 200
        assert limited.get("/v1/me", headers=headers(keys, "tech-b")).status_code == 200


def test_pg_provisioning_refuses_existing_data(pg_setup):
    _, settings, _ = pg_setup
    key_file = settings.postgres_secrets / "demo-credentials.json"
    before = key_file.read_bytes()
    with pytest.raises(RuntimeError, match="already exist"):
        seed_postgres(settings, FIXTURES)
    key_file.unlink()
    with pytest.raises(RuntimeError, match="not empty"):
        seed_postgres(settings, FIXTURES)
    assert not key_file.exists()
    key_file.write_bytes(before)
