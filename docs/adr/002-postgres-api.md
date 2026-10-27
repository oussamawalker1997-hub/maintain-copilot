# ADR-002 — Optional local PostgreSQL API with real site roles

Status: accepted for the two-site development demonstrator. Default remains SQLite.

## Decision

`MAINTAIN_BACKEND=postgres` selects an explicit backend; unknown names fail at configuration.
The same FastAPI routes, document lifecycle, applicability checks and ticket logic run
against a small repository boundary. SQL templates have driver-specific bound placeholders;
values are never interpolated. Inserts name columns, JSON is adapted to JSONB and booleans
to PostgreSQL types. SQLite FTS5/BM25 and PostgreSQL simple tsvector/ts_rank are separate
lexical implementations. Ranking and accent/token behavior can differ: this is contract
coverage on synthetic fixtures, not numerical retrieval equivalence or a quality benchmark.

## Identity and database authorization

Runtime reads only the two site passwords. Every request opens new connections with
`maintain_site_a` and `maintain_site_b`, looks up the bearer hash through each role's RLS,
and retains the uniquely matching site's repository for business operations. Both connections
close at request end. Missing, inactive or ambiguous credentials are rejected; failure of either
site connection fails closed. A request cannot select its site using a header, JSON field or
session setting. The selected connection does not change role or set a tenant GUC.

This deliberately bounded two-site router holds both passwords and can read both sites;
the backend remains trusted. It is not a scalable identity directory or an SSO design.
There is no pooling yet, avoiding reused tenant context; pooling and more sites need a new ADR.
Technician/editor checks and run ownership remain enforced by the API. Rate limits use
(site, principal id) so equal principal ids on different sites do not share a quota.

Startup checks both role mappings, absence of superuser/BYPASSRLS/role creation/database
creation/owner membership, and schema availability. `/healthz` reports `storage`. No runtime
DDL or fallback to SQLite occurs when PostgreSQL is unavailable. Error responses hide SQL,
credentials and document content.

## Transactions and concurrency

Each request owns its transaction. FastAPI's function-scoped dependency commits or rolls back
before the response is sent. All mutations acquire one PostgreSQL transaction advisory lock
per site, using the same lock in the dispatch worker and fixture provisioner. This intentionally
coarse serialization preserves local baseline idempotency, publication and revocation behavior.
Different sites use different locks. A direct SQL client that ignores these locks is outside this
application concurrency protocol; RLS and database constraints still apply.

This is not a high-throughput design. No throughput or latency improvement is claimed.
The outbox remains an atomic local simulator; it makes no remote exactly-once claim.

## Provisioning and existing data

`seed-postgres` is a separate, explicit administrative maintenance command. It requires the
PostgreSQL backend, migrated schema, empty business tables and no existing PostgreSQL key
file. It provisions synthetic fixtures in one database transaction and creates a new private
key file using exclusive creation and LF bytes. On ordinary errors it rolls back and removes
only the key file it just created. A process/host crash between filesystem and database commit
needs manual diagnosis: the two resources are not a distributed atomic transaction.

Neither provisioning nor serving opens the developer's SQLite file. Existing SQLite keys,
documents, run IDs and tickets are not transferred. A verified snapshot/import tool and
rollback drill are a separate milestone. SQLite backup is refused while PostgreSQL mode is
selected; PostgreSQL backup/restore qualification remains pending.

## Evidence and remaining limits

CI uses PostgreSQL 17 in a disposable volume on host port 25432. It tests real HTTP and CLI
operations, reuses 18 API contract scenarios, and checks concurrent ticket/worker idempotency,
revocation blocking, inactive/ambiguous tokens, duplicate principal IDs across sites,
transaction rollback after a deferred commit exception, backend outage and provisioning guards.
Destructive test resets require explicit disposable-test opt-in and the separate test port.
Normal tests skip those integration tests without this opt-in.

SQLite regression tests, ten public smoke cases and live loopback tests remain in Linux and
Windows CI. PDF isolation, production identity/secrets, retention, load tests, independent
retrieval evaluation, hybrid search and generation remain outside this change.
