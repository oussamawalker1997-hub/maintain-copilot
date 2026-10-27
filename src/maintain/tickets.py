"""Transactional outbox and an explicitly local CMMS simulator."""

import json
import uuid

from fastapi import HTTPException

from maintain.db import audit, digest, now
from maintain.retrieval import checked_run
from maintain.storage import repository


def create_ticket(db, principal, data, key):
    db = repository(db)
    payload_hash = digest(json.dumps(data.model_dump(), sort_keys=True))
    # Acquire write lock before checking: concurrent retries cannot create two effects.
    db.write_lock()
    prior = db.query(
        "SELECT * FROM tickets WHERE actor={p} AND idem_key={p}",
        (
            principal["id"],
            key,
        ),
    ).fetchone()
    if prior:
        if prior["payload_hash"] != payload_hash:
            raise HTTPException(409, "Idempotency key already used with a different payload")
        # An old replay must not reveal a ticket after membership has changed.
        checked_run(db, principal, prior["run_id"])
        return dict(prior)
    row, result = checked_run(db, principal, data.run_id)
    if row["asset_id"] != data.asset_id:
        raise HTTPException(422, "Run does not belong to this asset")
    if result["status"] != "evidence_found":
        raise HTTPException(409, "Only evidence-backed runs can create a ticket in v0.1")
    ticket_id = str(uuid.uuid4())
    db.insert(
        "tickets",
        dict(
            id=ticket_id,
            actor=principal["id"],
            asset_id=data.asset_id,
            run_id=data.run_id,
            idem_key=key,
            payload_hash=payload_hash,
            observations=data.observations,
            status="pending",
            created_at=now(),
        ),
    )
    db.insert("outbox", dict(ticket_id=ticket_id, created_at=now()))
    audit(db, principal["id"], "ticket.confirmed", ticket_id)
    return dict(db.query("SELECT * FROM tickets WHERE id={p}", (ticket_id,)).fetchone())


def dispatch(db):
    """Atomic local simulator. Not a claim about remote exactly-once delivery."""
    db = repository(db)
    db.write_lock()
    sent = 0
    for row in db.query("SELECT ticket_id FROM outbox ORDER BY created_at").fetchall():
        ticket = db.query("SELECT * FROM tickets WHERE id={p}", (row["ticket_id"],)).fetchone()
        principal = db.query(
            "SELECT * FROM principals WHERE id={p} AND active={p}", (ticket["actor"], True)
        ).fetchone()
        try:
            if not principal:
                raise HTTPException(403)
            checked_run(db, principal, ticket["run_id"])
        except HTTPException:
            db.query("UPDATE tickets SET status='blocked' WHERE id={p}", (ticket["id"],))
            audit(db, "worker", "ticket.blocked", ticket["id"])
        else:
            external_ref = "SIM-" + ticket["id"]
            db.insert(
                "simulated_work_orders",
                dict(external_ref=external_ref, ticket_id=ticket["id"]),
                ignore_conflict=True,
            )
            db.query(
                "UPDATE tickets SET status='sent',external_ref={p} WHERE id={p}",
                (external_ref, ticket["id"]),
            )
            audit(db, "worker", "ticket.simulated_delivery", ticket["id"])
            sent += 1
        db.query("DELETE FROM outbox WHERE ticket_id={p}", (ticket["id"],))
    return sent
