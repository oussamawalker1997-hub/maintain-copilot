-- Applied transactionally by scripts/postgres_local.py, as maintain_owner.
CREATE FUNCTION maintain.current_site() RETURNS text
LANGUAGE sql STABLE SET search_path = pg_catalog
AS $$ SELECT CASE current_user
  WHEN 'maintain_site_a' THEN 'DE-A'
  WHEN 'maintain_site_b' THEN 'DE-B'
  ELSE NULL END $$;
REVOKE ALL ON FUNCTION maintain.current_site() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION maintain.current_site() TO maintain_runtime;

CREATE TABLE maintain.sites (
  site text PRIMARY KEY CHECK (site IN ('DE-A', 'DE-B'))
);
CREATE TABLE maintain.principals (
  site text NOT NULL REFERENCES maintain.sites(site),
  id text NOT NULL,
  token_hash text NOT NULL,
  role text NOT NULL CHECK (role IN ('technician', 'editor')),
  active boolean NOT NULL DEFAULT true,
  PRIMARY KEY (site, id), UNIQUE (site, token_hash)
);
CREATE TABLE maintain.assets (
  site text NOT NULL REFERENCES maintain.sites(site), id text NOT NULL,
  model text NOT NULL, hardware text NOT NULL, firmware text NOT NULL,
  PRIMARY KEY (site, id)
);
CREATE TABLE maintain.documents (
  site text NOT NULL REFERENCES maintain.sites(site), id text NOT NULL,
  title text NOT NULL, family text NOT NULL, revision text NOT NULL,
  model text NOT NULL, hardware text NOT NULL,
  firmware_min text NOT NULL, firmware_max text NOT NULL,
  content_hash text NOT NULL,
  status text NOT NULL CHECK (status IN ('draft','published','superseded','revoked','quarantined')),
  reason text, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (site, id), UNIQUE (site, content_hash)
);
CREATE TABLE maintain.pages (
  site text NOT NULL, id bigint GENERATED ALWAYS AS IDENTITY,
  document_id text NOT NULL, number integer NOT NULL CHECK (number > 0), text text NOT NULL,
  search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, text)) STORED,
  PRIMARY KEY (site, id), UNIQUE (site, document_id, number),
  FOREIGN KEY (site, document_id) REFERENCES maintain.documents(site, id)
);
CREATE INDEX pages_search ON maintain.pages USING gin(search_vector);
CREATE TABLE maintain.runs (
  site text NOT NULL, id text NOT NULL, actor text NOT NULL, asset_id text NOT NULL,
  result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (site, id),
  FOREIGN KEY (site, actor) REFERENCES maintain.principals(site, id),
  FOREIGN KEY (site, asset_id) REFERENCES maintain.assets(site, id)
);
CREATE TABLE maintain.tickets (
  site text NOT NULL, id text NOT NULL, actor text NOT NULL, asset_id text NOT NULL,
  run_id text NOT NULL, idem_key text NOT NULL, payload_hash text NOT NULL,
  observations text NOT NULL,
  status text NOT NULL CHECK (status IN ('pending','sent','blocked')),
  external_ref text, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (site, id), UNIQUE (site, actor, idem_key),
  FOREIGN KEY (site, actor) REFERENCES maintain.principals(site, id),
  FOREIGN KEY (site, asset_id) REFERENCES maintain.assets(site, id),
  FOREIGN KEY (site, run_id) REFERENCES maintain.runs(site, id)
);
CREATE TABLE maintain.outbox (
  site text NOT NULL, ticket_id text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (site, ticket_id),
  FOREIGN KEY (site, ticket_id) REFERENCES maintain.tickets(site, id)
);
CREATE TABLE maintain.simulated_work_orders (
  site text NOT NULL, external_ref text NOT NULL, ticket_id text NOT NULL,
  PRIMARY KEY (site, external_ref), UNIQUE (site, ticket_id),
  FOREIGN KEY (site, ticket_id) REFERENCES maintain.tickets(site, id)
);
CREATE TABLE maintain.feedback (
  site text NOT NULL, id text NOT NULL, run_id text NOT NULL, actor text NOT NULL,
  useful boolean NOT NULL, reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (site, id),
  FOREIGN KEY (site, run_id) REFERENCES maintain.runs(site, id),
  FOREIGN KEY (site, actor) REFERENCES maintain.principals(site, id)
);
CREATE TABLE maintain.audit (
  site text NOT NULL REFERENCES maintain.sites(site), id bigint GENERATED ALWAYS AS IDENTITY,
  actor text NOT NULL, event text NOT NULL, object_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (site, id)
);

-- Enforce policies even for table owners. Runtime has no table ownership, DDL or TRUNCATE.
DO $policies$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'sites','principals','assets','documents','pages','runs','tickets','outbox',
    'simulated_work_orders','feedback','audit'
  ] LOOP
    EXECUTE format('ALTER TABLE maintain.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE maintain.%I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format(
      'CREATE POLICY site_scope ON maintain.%I TO maintain_runtime '
      'USING (site = maintain.current_site()) WITH CHECK (site = maintain.current_site())',
      table_name
    );
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON maintain.%I TO maintain_runtime',
                   table_name);
  END LOOP;
END $policies$;
REVOKE INSERT, UPDATE, DELETE ON maintain.sites FROM maintain_runtime;
REVOKE UPDATE, DELETE ON maintain.audit FROM maintain_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA maintain TO maintain_runtime;
CREATE INDEX documents_scope ON maintain.documents(site, status, model, hardware);
CREATE INDEX audit_time ON maintain.audit(site, created_at);
