"""Transactional outbox and an explicitly local CMMS simulator."""

import json
import uuid

from fastapi import HTTPException

from maintain.db import audit, digest, now
from maintain.retrieval import checked_run


def create_ticket(db, principal, data, key):
    payload_hash = digest(json.dumps(data.model_dump(), sort_keys=True))
    # Acquire write lock before checking: concurrent retries cannot create two effects.
    db.execute("BEGIN IMMEDIATE")
    prior = db.execute(
        "SELECT * FROM tickets WHERE actor=? AND idem_key=?",
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
    db.execute(
        """INSERT INTO tickets(id,actor,asset_id,run_id,idem_key,payload_hash,
        observations,status,created_at) VALUES(?,?,?,?,?,?,?,'pending',?)""",
        (
            ticket_id,
            principal["id"],
            data.asset_id,
            data.run_id,
            key,
            payload_hash,
            data.observations,
            now(),
        ),
    )
    db.execute("INSERT INTO outbox VALUES(?,?)", (ticket_id, now()))
    audit(db, principal["id"], "ticket.confirmed", ticket_id)
    return dict(db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone())


def dispatch(db):
    """Atomic local simulator. Not a claim about remote exactly-once delivery."""
    db.execute("BEGIN IMMEDIATE")
    sent = 0
    for row in db.execute("SELECT ticket_id FROM outbox ORDER BY created_at").fetchall():
        ticket = db.execute("SELECT * FROM tickets WHERE id=?", (row["ticket_id"],)).fetchone()
        principal = db.execute(
            "SELECT * FROM principals WHERE id=? AND active=1", (ticket["actor"],)
        ).fetchone()
        try:
            if not principal:
                raise HTTPException(403)
            checked_run(db, principal, ticket["run_id"])
        except HTTPException:
            db.execute("UPDATE tickets SET status='blocked' WHERE id=?", (ticket["id"],))
            audit(db, "worker", "ticket.blocked", ticket["id"])
        else:
            external_ref = "SIM-" + ticket["id"]
            db.execute(
                "INSERT OR IGNORE INTO simulated_work_orders VALUES(?,?)",
                (external_ref, ticket["id"]),
            )
            db.execute(
                "UPDATE tickets SET status='sent',external_ref=? WHERE id=?",
                (external_ref, ticket["id"]),
            )
            audit(db, "worker", "ticket.simulated_delivery", ticket["id"])
            sent += 1
        db.execute("DELETE FROM outbox WHERE ticket_id=?", (ticket["id"],))
    return sent
