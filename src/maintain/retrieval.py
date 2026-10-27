"""B0 lexical search. No LLM, embedding model or semantic confidence claims."""

import json
import re
import uuid

from fastapi import HTTPException

from maintain.db import audit, now
from maintain.models import version

STOPWORDS = set(
    "que quoi quel quelle quelles le la les de des du un une et est signifie "
    "what is the a an and does mean der die das was bedeutet und ein eine "
    "comment how pourquoi why informations information relever".split()
)


def asset_for(db, principal, asset_id):
    asset = db.query(
        "SELECT * FROM assets WHERE id={p} AND site={p}", (asset_id, principal["site"])
    ).fetchone()
    if not asset:
        raise HTTPException(404, "Not found")
    return asset


def applicable(doc, asset):
    return (
        doc["model"] == asset["model"]
        and doc["hardware"] == asset["hardware"]
        and version(doc["firmware_min"])
        <= version(asset["firmware"])
        <= version(doc["firmware_max"])
    )


def search(db, principal, asset, question):
    terms = [t for t in re.findall(r"\w+", question.lower()) if t not in STOPWORDS][:32]
    codes = re.findall(r"\b[eE]\d{3}\b", question)
    if not terms:
        return []
    rows = db.search_pages(terms, principal["site"], asset["model"], asset["hardware"])
    results = []
    for row in rows:
        if not applicable(row, asset):
            continue
        if codes and not any(
            re.search(r"\b" + re.escape(c) + r"\b", row["text"], re.I) for c in codes
        ):
            continue
        results.append(
            {
                "document_id": row["id"],
                "title": row["title"],
                "family": row["family"],
                "revision": row["revision"],
                "page": row["number"],
                "text": row["text"],
            }
        )
    return results


def make_answer(db, principal, data):
    asset = asset_for(db, principal, data.asset_id)
    result = {
        "run_id": str(uuid.uuid4()),
        "status": "evidence_found",
        "mode": "lexical_baseline",
        "sources": [],
        "limitations": [
            "Synthetic demonstration. Source excerpts are not a validated diagnosis.",
            "No LLM or semantic entailment verification is used in this version.",
        ],
    }
    if not asset["firmware"] or not asset["hardware"]:
        result.update(status="needs_clarification", reason="Confirm hardware and firmware")
    else:
        found = search(db, principal, asset, data.question)
        families = {}
        for item in found:
            families.setdefault(item["family"], set()).add(item["revision"])
        if any(len(revisions) > 1 for revisions in families.values()):
            result.update(status="abstained", reason="Conflicting applicable document revisions")
        elif not found:
            result.update(status="abstained", reason="No applicable lexical evidence found")
        else:
            result["sources"] = found[:5]
    db.insert(
        "runs",
        dict(
            id=result["run_id"],
            actor=principal["id"],
            asset_id=data.asset_id,
            result=json.dumps(result, ensure_ascii=False),
            created_at=now(),
        ),
    )
    audit(db, principal["id"], "search." + result["status"], result["run_id"])
    return result


def checked_run(db, principal, run_id):
    row = db.query(
        "SELECT * FROM runs WHERE id={p} AND actor={p}",
        (
            run_id,
            principal["id"],
        ),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    asset = asset_for(db, principal, row["asset_id"])
    result = row["result"] if isinstance(row["result"], dict) else json.loads(row["result"])
    for source in result["sources"]:
        doc = db.query(
            "SELECT * FROM documents WHERE id={p} AND site={p} AND status='published'",
            (source["document_id"], principal["site"]),
        ).fetchone()
        if not doc or not applicable(doc, asset):
            raise HTTPException(409, "Evidence changed or was revoked; search again")
    return row, result
