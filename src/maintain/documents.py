import base64
import binascii
import hashlib
import io
import json
import uuid

from fastapi import HTTPException
from pypdf import PdfReader

from maintain.db import audit, now
from maintain.models import DocumentRequest
from maintain.storage import repository


def ingest(db, principal, data: DocumentRequest):
    db = repository(db)
    pages = data.pages
    reason = None
    if pages is None:
        try:
            raw = base64.b64decode(data.pdf_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(422, "Invalid base64") from exc
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(413, "PDF exceeds 20 MiB")
        if not raw.startswith(b"%PDF-"):
            raise HTTPException(422, "Not a PDF")
        try:
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF")
            if len(reader.pages) > 500:
                raise HTTPException(413, "PDF exceeds 500 pages")
            pages = []
            for page in reader.pages:
                # This is an extraction guard, not a sandbox. Local trusted files only in v0.1.
                stream = page.get_contents()
                if stream is not None and len(stream.get_data()) > 5_000_000:
                    raise ValueError("Page content exceeds extraction limit")
                pages.append(page.extract_text() or "")
            if sum(map(len, pages)) > 2_000_000:
                raise ValueError("Extracted text exceeds limit")
        except HTTPException:
            raise
        except Exception:
            pages = []
            reason = "PDF extraction failed; review the source locally"
        identity = raw
    else:
        identity = json.dumps(pages, ensure_ascii=False).encode()
    content_hash = hashlib.sha256(identity).hexdigest()
    existing = db.query(
        "SELECT * FROM documents WHERE site={p} AND content_hash={p}",
        (principal["site"], content_hash),
    ).fetchone()
    if existing:
        # A duplicate cannot silently replace trusted metadata.
        for field in ("family", "revision", "model", "hardware", "firmware_min", "firmware_max"):
            if existing[field] != getattr(data, field):
                raise HTTPException(409, "Identical content has different applicability metadata")
        return {"id": existing["id"], "status": existing["status"], "duplicate": True}
    if not pages or any(len(p.strip()) < 10 for p in pages):
        reason = reason or "One or more pages have insufficient text; OCR/review required"
    document_id = str(uuid.uuid4())
    status = "quarantined" if reason else "draft"
    db.insert(
        "documents",
        dict(
            id=document_id,
            site=principal["site"],
            title=data.title,
            family=data.family,
            revision=data.revision,
            model=data.model,
            hardware=data.hardware,
            firmware_min=data.firmware_min,
            firmware_max=data.firmware_max,
            content_hash=content_hash,
            status=status,
            reason=reason,
            created_at=now(),
        ),
    )
    for number, text in enumerate(pages or [], 1):
        db.insert("pages", dict(document_id=document_id, number=number, text=text))
    audit(db, principal["id"], "document.ingested", document_id)
    return {"id": document_id, "status": status, "reason": reason, "duplicate": False}


def scoped_document(db, principal, document_id):
    row = db.query(
        "SELECT * FROM documents WHERE id={p} AND site={p}", (document_id, principal["site"])
    ).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    return row
