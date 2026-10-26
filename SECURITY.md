# Security and supported use

v0.1 supports a trusted local synthetic demonstration. It is not approved for internet exposure or industrial use. Never use its fictional documents to operate machinery.

Credentials are randomly generated, hashed in the database and held only in memory by the browser. `.local/` and `.env` are excluded from Git and release ZIPs. On Windows, filesystem protection also depends on the user account and directory ACLs; POSIX mode bits are not an ACL guarantee.

API scope enforcement is application-level; the SQLite database is not a tenant boundary. Direct database access bypasses application permissions. PDF extraction is not sandboxed, so only trusted files are supported. The database and backups contain source text and ticket observations. No enterprise encryption-at-rest, SSO, immutable audit or automated deletion policy is claimed.

If you discover a vulnerability, do not include keys, private documents or exploit payloads with private data in a public issue. After GitHub publication, enable the repository's private vulnerability reporting feature and use it. Until then, keep the repository private for review.
