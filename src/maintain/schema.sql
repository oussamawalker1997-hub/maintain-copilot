PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
CREATE TABLE IF NOT EXISTS principals (
 id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
 site TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('technician','editor')),
 active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS assets (
 id TEXT PRIMARY KEY, site TEXT NOT NULL, model TEXT NOT NULL,
 hardware TEXT NOT NULL, firmware TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, site TEXT NOT NULL, title TEXT NOT NULL, family TEXT NOT NULL,
 revision TEXT NOT NULL, model TEXT NOT NULL, hardware TEXT NOT NULL,
 firmware_min TEXT NOT NULL, firmware_max TEXT NOT NULL,
 content_hash TEXT NOT NULL, status TEXT NOT NULL
 CHECK(status IN ('draft','published','superseded','revoked','quarantined')),
 reason TEXT, created_at TEXT NOT NULL,
 UNIQUE(site, content_hash)
);
CREATE TABLE IF NOT EXISTS pages (
 id INTEGER PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 number INTEGER NOT NULL, text TEXT NOT NULL,
 UNIQUE(document_id, number)
);
CREATE VIRTUAL TABLE IF NOT EXISTS page_fts USING fts5(text, content='pages', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
 INSERT INTO page_fts(rowid,text) VALUES(new.id,new.text);
END;
CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
 INSERT INTO page_fts(page_fts,rowid,text) VALUES('delete',old.id,old.text);
END;
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, actor TEXT NOT NULL REFERENCES principals(id),
 asset_id TEXT NOT NULL REFERENCES assets(id), result TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
 id TEXT PRIMARY KEY, actor TEXT NOT NULL REFERENCES principals(id),
 asset_id TEXT NOT NULL REFERENCES assets(id), run_id TEXT NOT NULL REFERENCES runs(id),
 idem_key TEXT NOT NULL, payload_hash TEXT NOT NULL, observations TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','sent','blocked')),
 external_ref TEXT, created_at TEXT NOT NULL, UNIQUE(actor,idem_key)
);
CREATE TABLE IF NOT EXISTS outbox (
 ticket_id TEXT PRIMARY KEY REFERENCES tickets(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS simulated_work_orders (
 external_ref TEXT PRIMARY KEY, ticket_id TEXT NOT NULL UNIQUE REFERENCES tickets(id)
);
CREATE TABLE IF NOT EXISTS feedback (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
 actor TEXT NOT NULL REFERENCES principals(id), useful INTEGER NOT NULL,
 reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, actor TEXT NOT NULL, event TEXT NOT NULL,
 object_id TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS documents_scope ON documents(site,status,model,hardware);
CREATE INDEX IF NOT EXISTS audit_time ON audit(created_at);
