import base64
import io

from conftest import headers, question
from pypdf import PdfWriter


def document(**changes):
    data = dict(
        title="Test manual",
        family="TEST",
        revision="1",
        model="NW-Conveyor-C2",
        hardware="rev-B",
        firmware_min="2.0",
        firmware_max="2.9",
        pages=["E042: Original synthetic test evidence, not real maintenance guidance."],
    )
    return data | changes


def upload(client, keys, data):
    return client.post("/v1/documents", headers=headers(keys, "editor-a"), json=data)


def test_editor_required_for_ingestion(setup):
    client, _, keys = setup
    assert client.post("/v1/documents", headers=headers(keys), json=document()).status_code == 403


def test_draft_requires_explicit_publication_and_duplicate_is_idempotent(setup):
    client, _, keys = setup
    data = document(pages=["E321: A synthetic diagnostic observation for testing only."])
    result = upload(client, keys, data).json()
    assert result["status"] == "draft"
    assert question(client, keys, "E321").json()["status"] == "abstained"
    duplicate = upload(client, keys, data).json()
    assert duplicate["id"] == result["id"] and duplicate["duplicate"]
    assert (
        client.post(
            f"/v1/documents/{result['id']}/publish", headers=headers(keys, "editor-a")
        ).status_code
        == 200
    )
    assert question(client, keys, "E321").json()["status"] == "evidence_found"


def test_duplicate_metadata_mismatch_does_not_override(setup):
    client, _, keys = setup
    assert upload(client, keys, document()).status_code == 201
    assert upload(client, keys, document(hardware="rev-A")).status_code == 409


def test_empty_and_image_only_documents_quarantined(setup):
    client, _, keys = setup
    result = upload(
        client, keys, document(pages=["", "A readable second page for the test."])
    ).json()
    assert result["status"] == "quarantined"
    assert (
        client.post(
            f"/v1/documents/{result['id']}/publish", headers=headers(keys, "editor-a")
        ).status_code
        == 409
    )
    writer, stream = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=100, height=100)
    writer.write(stream)
    payload = document()
    del payload["pages"]
    payload["pdf_base64"] = base64.b64encode(stream.getvalue()).decode()
    assert upload(client, keys, payload).json()["status"] == "quarantined"


def test_invalid_ranges_and_ambiguous_inputs_rejected(setup):
    client, _, keys = setup
    for payload in (
        document(firmware_min="2.10", firmware_max="2.9"),
        document(pdf_base64="bad"),
        document(firmware_min="latest"),
    ):
        assert upload(client, keys, payload).status_code == 422


def test_partial_overlap_conflict_abstains(setup):
    client, _, keys = setup
    payload = document(
        family="C2-MAN",
        revision="4",
        firmware_min="2.3",
        firmware_max="3.0",
        pages=["E042: A different test revision requires review."],
    )
    doc = upload(client, keys, payload).json()
    assert (
        client.post(
            f"/v1/documents/{doc['id']}/publish", headers=headers(keys, "editor-a")
        ).status_code
        == 200
    )
    result = question(client, keys).json()
    assert result["status"] == "abstained"
    assert result["sources"] == []


def test_exact_range_supersedes_previous_revision(setup):
    client, _, keys = setup
    doc = upload(client, keys, document(family="C2-MAN", revision="4")).json()
    client.post(f"/v1/documents/{doc['id']}/publish", headers=headers(keys, "editor-a"))
    result = question(client, keys).json()
    assert all(s["revision"] != "3" for s in result["sources"])
    assert any(s["revision"] == "4" for s in result["sources"])
