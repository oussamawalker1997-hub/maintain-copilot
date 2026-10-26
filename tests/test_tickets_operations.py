import json
import os
from concurrent.futures import ThreadPoolExecutor

from conftest import headers, question
from fastapi.testclient import TestClient

from maintain.app import create_app
from maintain.cli import backup, seed
from maintain.config import Settings
from maintain.db import connect
from maintain.tickets import dispatch


def ticket_payload(result):
    return {
        "run_id": result["run_id"],
        "asset_id": "NW-P17",
        "observations": "Synthetic alarm observed at 08:15",
        "confirmed": True,
    }


def test_confirmation_and_run_asset_match_required(setup):
    client, _, keys = setup
    body = ticket_payload(question(client, keys).json())
    auth = headers(keys) | {"Idempotency-Key": "test-confirm-1"}
    assert (
        client.post("/v1/tickets", headers=auth, json=body | {"confirmed": False}).status_code
        == 422
    )
    assert (
        client.post("/v1/tickets", headers=auth, json=body | {"asset_id": "NW-P18"}).status_code
        == 422
    )


def test_concurrent_replays_and_dispatch_have_one_effect(setup):
    client, database, keys = setup
    body = ticket_payload(question(client, keys).json())
    auth = headers(keys) | {"Idempotency-Key": "test-replay-1"}
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
    with connect(database) as db:
        assert dispatch(db) == 1
    with connect(database) as db:
        assert dispatch(db) == 0
        assert db.execute("SELECT count(*) FROM simulated_work_orders").fetchone()[0] == 1
    ticket = responses[0].json()["id"]
    assert client.get(f"/v1/tickets/{ticket}", headers=headers(keys)).json()["status"] == "sent"
    assert client.get(f"/v1/tickets/{ticket}", headers=headers(keys, "tech-b")).status_code == 404


def test_revoked_source_blocks_pending_delivery(setup):
    client, database, keys = setup
    run = question(client, keys).json()
    response = client.post(
        "/v1/tickets",
        headers=headers(keys) | {"Idempotency-Key": "revoke-1"},
        json=ticket_payload(run),
    )
    doc = run["sources"][0]["document_id"]
    client.post(f"/v1/documents/{doc}/revoke", headers=headers(keys, "editor-a"))
    with connect(database) as db:
        assert dispatch(db) == 0
        assert (
            db.execute(
                "SELECT status FROM tickets WHERE id=?", (response.json()["id"],)
            ).fetchone()[0]
            == "blocked"
        )


def test_backup_restores_search_data(setup, tmp_path):
    client, database, keys = setup
    backup_path = tmp_path / "backup.sqlite"
    backup(database, backup_path)
    with TestClient(create_app(Settings(backup_path))) as restored:
        assert question(restored, keys).json()["status"] == "evidence_found"
    # POSIX mode bits do not validate Windows ACLs. Restoration is tested on both.
    if os.name == "posix":
        assert backup_path.stat().st_mode & 0o077 == 0


def test_health_ui_headers_and_body_limit(setup):
    client, database, _ = setup
    assert client.get("/").status_code == 200
    assert client.get("/app.js").status_code == 200
    assert client.get("/healthz").json()["mode"] == "lexical_baseline"
    response = client.get("/")
    assert response.headers["X-Trace-ID"]
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    with TestClient(create_app(Settings(database, max_body_bytes=100))) as limited:
        assert limited.post("/v1/answers", content=b"x" * 101).status_code == 413


def test_invalid_payload_does_not_echo_sensitive_input(setup):
    client, _, keys = setup
    response = client.post(
        "/v1/answers",
        headers=headers(keys),
        json={
            "asset_id": "NW-P17",
            "question": "E042",
            "secret": "SENTINEL_NO_ECHO",
        },
    )
    assert response.status_code == 422
    assert "SENTINEL_NO_ECHO" not in response.text


def test_rate_limit(setup):
    _, database, keys = setup
    with TestClient(create_app(Settings(database, requests_per_minute=1))) as client:
        assert client.get("/v1/me", headers=headers(keys)).status_code == 200
        assert client.get("/v1/me", headers=headers(keys)).status_code == 429


def test_seed_does_not_overwrite_existing_credentials(setup):
    _, database, keys = setup
    import pytest

    with pytest.raises(SystemExit):
        seed(database, database.parent)
    assert (
        json.loads((database.parent / "demo-credentials.json").read_text(encoding="utf-8")) == keys
    )
