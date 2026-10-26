import json
from concurrent.futures import ThreadPoolExecutor

from conftest import headers, question

from maintain.db import connect


def test_no_token_and_invalid_token_are_rejected(setup):
    client, _, _ = setup
    assert client.get("/v1/assets").status_code == 401
    assert (
        client.get("/v1/assets", headers={"Authorization": "Bearer " + "x" * 30}).status_code == 401
    )


def test_scope_applies_to_assets_search_and_pages(setup):
    client, _, keys = setup
    assert all(a["site"] == "DE-A" for a in client.get("/v1/assets", headers=headers(keys)).json())
    assert question(client, keys, asset="NW-B01").status_code == 404
    docs = client.get("/v1/documents", headers=headers(keys, "tech-b")).json()["items"]
    doc = docs[0]["id"]
    response = client.get(f"/v1/documents/{doc}/pages/1", headers=headers(keys))
    assert response.status_code == 404
    assert "B_PRIVATE" not in response.text
    result = question(client, keys).json()
    assert "B_PRIVATE" not in json.dumps(result)
    assert "OLD_VARIANT" not in json.dumps(result)


def test_versions_are_numeric_and_sources_applicable(setup):
    client, _, keys = setup
    result = question(client, keys).json()
    assert result["status"] == "evidence_found"
    assert result["mode"] == "lexical_baseline"
    assert any(s["revision"] == "3" and s["page"] == 2 for s in result["sources"])
    old = question(client, keys, asset="NW-P18").json()
    assert old["sources"][0]["revision"] == "1"


def test_unknown_codes_abstain_even_with_common_words(setup):
    client, _, keys = setup
    result = question(client, keys, "Que signifie E099 capteur ?").json()
    assert result["status"] == "abstained"
    assert result["sources"] == []


def test_incomplete_variant_requires_clarification(setup):
    client, _, keys = setup
    assert question(client, keys, asset="NW-P19").json()["status"] == "needs_clarification"


def test_fts_operators_are_treated_as_data(setup):
    client, _, keys = setup
    for text in ('" OR *', "NEAR(foo)", "'; DROP TABLE assets; --"):
        assert question(client, keys, text).status_code == 200
    assert len(client.get("/v1/assets", headers=headers(keys)).json()) == 3


def test_run_private_and_source_revocation_invalidates_history(setup):
    client, _, keys = setup
    result = question(client, keys).json()
    assert (
        client.get(f"/v1/runs/{result['run_id']}", headers=headers(keys, "tech-b")).status_code
        == 404
    )
    doc = result["sources"][0]["document_id"]
    assert (
        client.post(f"/v1/documents/{doc}/revoke", headers=headers(keys, "editor-a")).status_code
        == 200
    )
    assert client.get(f"/v1/runs/{result['run_id']}", headers=headers(keys)).status_code == 409
    assert client.get(f"/v1/documents/{doc}/pages/2", headers=headers(keys)).status_code == 404


def test_revoked_credential_is_immediately_rejected(setup):
    client, database, keys = setup
    with connect(database) as db:
        db.execute("UPDATE principals SET active=0 WHERE id='tech-a'")
    assert question(client, keys).status_code == 401


def test_question_text_not_stored_in_run_or_audit(setup):
    client, database, keys = setup
    sentinel = "PRIVATE_QUERY_391 E042"
    assert question(client, keys, sentinel).status_code == 200
    with connect(database) as db:
        assert sentinel not in str([tuple(r) for r in db.execute("SELECT * FROM runs")])
        assert sentinel not in str([tuple(r) for r in db.execute("SELECT * FROM audit")])


def test_parallel_site_searches_do_not_mix_context(setup):
    client, _, keys = setup

    def perform(user):
        return client.post(
            "/v1/answers",
            headers=headers(keys, user),
            json={
                "asset_id": "NW-P17" if user == "tech-a" else "NW-B01",
                "question": "E042",
            },
        ).json()

    users = ["tech-a", "tech-b"] * 5
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(perform, users))
    for user, result in zip(users, results, strict=True):
        assert result["status"] == "evidence_found"
        assert ("B_PRIVATE" in json.dumps(result)) == (user == "tech-b")
