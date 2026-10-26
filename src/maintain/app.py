import logging
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from maintain.config import Settings
from maintain.db import audit, connect, digest, initialize, now
from maintain.documents import ingest, scoped_document
from maintain.models import AnswerRequest, DocumentRequest, FeedbackRequest, TicketRequest
from maintain.retrieval import checked_run, make_answer
from maintain.tickets import create_ticket

LOG = logging.getLogger("maintain.requests")
WEB = Path(__file__).parent / "web"


class BodyLimit:
    def __init__(self, app, limit):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                response = JSONResponse({"error": {"code": "BODY_TOO_LARGE"}}, 413)
                return await response(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        initialize(settings.database)
        yield

    app = FastAPI(
        title="MAINTAIN", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.add_middleware(BodyLimit, limit=settings.max_body_bytes)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )
    limiter = defaultdict(deque)
    lock = threading.Lock()

    @app.middleware("http")
    async def trace(request: Request, call_next):
        started = time.monotonic()
        request.state.trace_id = str(uuid.uuid4())
        try:
            response = await call_next(request)
        except Exception:
            # No exception payload: it can contain document text or credentials.
            response = JSONResponse(
                {"error": {"code": "INTERNAL_ERROR", "trace_id": request.state.trace_id}}, 500
            )
        response.headers["X-Trace-ID"] = request.state.trace_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        route = request.scope.get("route")
        LOG.info(
            "trace=%s route=%s status=%s duration_ms=%.2f",
            request.state.trace_id,
            getattr(route, "path", "unmatched"),
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": str(exc.status_code),
                    "message": exc.detail,
                    "trace_id": request.state.trace_id,
                }
            },
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "fields": [list(e["loc"]) for e in exc.errors()],
                    "trace_id": request.state.trace_id,
                }
            },
            422,
        )

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "DATABASE_UNAVAILABLE",
                    "trace_id": request.state.trace_id,
                }
            },
            503,
        )

    def session():
        with connect(settings.database) as db:
            yield db

    # Commit/rollback before sending a success response, not after streaming the body.
    DB = Annotated[sqlite3.Connection, Depends(session, scope="function")]

    def authenticate(db: DB, authorization: Annotated[str | None, Header()] = None):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"}
            )
        token = authorization[7:]
        if not 20 <= len(token) <= 256:
            raise HTTPException(401, "Invalid token")
        row = db.execute(
            "SELECT * FROM principals WHERE token_hash=? AND active=1", (digest(token),)
        ).fetchone()
        if not row:
            raise HTTPException(401, "Invalid token")
        with lock:
            queue = limiter[row["id"]]
            t = time.monotonic()
            while queue and queue[0] < t - 60:
                queue.popleft()
            if len(queue) >= settings.requests_per_minute:
                raise HTTPException(429, "Request limit reached", headers={"Retry-After": "60"})
            queue.append(t)
        return row

    Principal = Annotated[sqlite3.Row, Depends(authenticate)]

    def editor(principal: Principal):
        if principal["role"] != "editor":
            raise HTTPException(403, "Editor role required")
        return principal

    Editor = Annotated[sqlite3.Row, Depends(editor)]

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(WEB / "index.html")

    @app.get("/app.js", include_in_schema=False)
    def javascript():
        return FileResponse(WEB / "app.js", media_type="text/javascript")

    @app.get("/styles.css", include_in_schema=False)
    def stylesheet():
        return FileResponse(WEB / "styles.css", media_type="text/css")

    @app.get("/docs", include_in_schema=False)
    def api_docs():
        return FileResponse(WEB / "api.html")

    @app.get("/healthz")
    def health(db: DB):
        db.execute("SELECT 1").fetchone()
        return {"status": "ok", "version": "0.1.0", "mode": "lexical_baseline"}

    @app.get("/v1/me")
    def me(principal: Principal):
        return {k: principal[k] for k in ("id", "site", "role")}

    @app.get("/v1/assets")
    def assets(db: DB, principal: Principal):
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM assets WHERE site=? ORDER BY id", (principal["site"],)
            )
        ]

    @app.post("/v1/answers")
    def answers(data: AnswerRequest, db: DB, principal: Principal):
        db.execute("BEGIN IMMEDIATE")
        return make_answer(db, principal, data)

    @app.get("/v1/runs/{run_id}")
    def run(run_id: str, db: DB, principal: Principal):
        _, result = checked_run(db, principal, run_id)
        return result

    @app.get("/v1/documents")
    def documents(db: DB, principal: Principal, offset: int = 0, limit: int = 20):
        if offset < 0 or not 1 <= limit <= 100:
            raise HTTPException(422, "Invalid pagination")
        fields = "id,title,family,revision,model,hardware,firmware_min,firmware_max,status,reason"
        condition = "" if principal["role"] == "editor" else " AND status='published'"
        rows = db.execute(
            f"SELECT {fields} FROM documents WHERE site=?{condition} ORDER BY id LIMIT ? OFFSET ?",
            (principal["site"], limit, offset),
        ).fetchall()
        return {"items": [dict(r) for r in rows], "offset": offset, "limit": limit}

    @app.post("/v1/documents", status_code=201)
    def upload(data: DocumentRequest, db: DB, principal: Editor):
        db.execute("BEGIN IMMEDIATE")
        return ingest(db, principal, data)

    @app.post("/v1/documents/{document_id}/publish")
    def publish(document_id: str, db: DB, principal: Editor):
        db.execute("BEGIN IMMEDIATE")
        doc = scoped_document(db, principal, document_id)
        if doc["status"] != "draft":
            raise HTTPException(409, "Only a reviewed draft may be published")
        same = db.execute(
            """SELECT id FROM documents WHERE site=? AND family=? AND revision=?
            AND model=? AND hardware=? AND status='published'""",
            (doc["site"], doc["family"], doc["revision"], doc["model"], doc["hardware"]),
        ).fetchone()
        if same:
            raise HTTPException(409, "A published revision already exists; review metadata")
        # Supersede only precisely identical applicability, retaining older hardware ranges.
        db.execute(
            """UPDATE documents SET status='superseded' WHERE site=? AND family=?
            AND model=? AND hardware=? AND firmware_min=? AND firmware_max=?
            AND status='published'""",
            tuple(
                doc[k]
                for k in ("site", "family", "model", "hardware", "firmware_min", "firmware_max")
            ),
        )
        db.execute("UPDATE documents SET status='published' WHERE id=?", (document_id,))
        audit(db, principal["id"], "document.published", document_id)
        return {"id": document_id, "status": "published"}

    @app.post("/v1/documents/{document_id}/revoke")
    def revoke(document_id: str, db: DB, principal: Editor):
        scoped_document(db, principal, document_id)
        db.execute("UPDATE documents SET status='revoked' WHERE id=?", (document_id,))
        audit(db, principal["id"], "document.revoked", document_id)
        return {"id": document_id, "status": "revoked"}

    @app.get("/v1/documents/{document_id}/pages/{number}")
    def page(document_id: str, number: int, db: DB, principal: Principal):
        doc = scoped_document(db, principal, document_id)
        if principal["role"] != "editor" and doc["status"] != "published":
            raise HTTPException(404, "Not found")
        row = db.execute(
            "SELECT text FROM pages WHERE document_id=? AND number=?",
            (
                document_id,
                number,
            ),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        return {
            "document_id": document_id,
            "title": doc["title"],
            "revision": doc["revision"],
            "page": number,
            "text": row["text"],
        }

    @app.post("/v1/tickets", status_code=202)
    def tickets(
        data: TicketRequest,
        db: DB,
        principal: Principal,
        idempotency_key: Annotated[str, Header(min_length=8, max_length=100)],
    ):
        ticket = create_ticket(db, principal, data, idempotency_key)
        return {k: ticket[k] for k in ("id", "status", "external_ref")}

    @app.get("/v1/tickets/{ticket_id}")
    def ticket_status(ticket_id: str, db: DB, principal: Principal):
        row = db.execute(
            "SELECT * FROM tickets WHERE id=? AND actor=?",
            (
                ticket_id,
                principal["id"],
            ),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        checked_run(db, principal, row["run_id"])
        return {k: row[k] for k in ("id", "asset_id", "status", "external_ref", "created_at")}

    @app.post("/v1/feedback", status_code=201)
    def feedback(data: FeedbackRequest, db: DB, principal: Principal):
        checked_run(db, principal, data.run_id)
        feedback_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO feedback VALUES(?,?,?,?,?,?)",
            (
                feedback_id,
                data.run_id,
                principal["id"],
                int(data.useful),
                data.reason,
                now(),
            ),
        )
        audit(db, principal["id"], "feedback.created", feedback_id)
        return {"id": feedback_id}

    @app.get("/v1/audit")
    def audit_events(db: DB, principal: Editor, limit: int = 50):
        if not 1 <= limit <= 100:
            raise HTTPException(422, "Invalid limit")
        rows = db.execute(
            """SELECT a.event,a.object_id,a.created_at FROM audit a
            JOIN principals p ON a.actor=p.id WHERE p.site=? ORDER BY a.id DESC LIMIT ?""",
            (principal["site"], limit),
        ).fetchall()
        return [dict(row) for row in rows]

    return app
