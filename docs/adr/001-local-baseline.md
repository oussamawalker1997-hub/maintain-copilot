# ADR-001 — Offline local baseline before a model integration

Status: accepted for v0.1, not an enterprise deployment decision.

Context: the mission targets a one-person demonstrator and ultimately PostgreSQL, hybrid retrieval and evaluated synthesis. A model API, separate front-end build system and distributed infrastructure would prevent validating the first full workflow on a learner's machine without additional accounts.

Options: full target architecture immediately; notebook-only prototype; a versioned API and browser workbench with a local lexical baseline.

Decision: implement the third option using FastAPI, SQLite FTS5, a small same-origin interface and original synthetic fixtures. Use BM25 only for lexical ordering. Do not call a search hit a generated answer or a similarity score a calibrated confidence. Use numeric firmware tuples rather than string comparison. Bind locally by default.

Consequences: local installation and tests are inexpensive, data provenance is controlled, and the API workflow is testable. There is no SQL RLS, semantic retrieval, industrial validation or distributed scalability. SQLite serializes write transactions; searches currently record runs under a write lock, deliberately limiting throughput. FTS statistics span both sites, so this is not strict multi-tenant statistical isolation.

Revision trigger: start PostgreSQL migration before private enterprise documents, multiple deployments or a meaningful pilot. Keep the API acceptance tests; replace persistence and extend tests to actual database roles and permissions. Add embedding and LLM adapters only after baselines and evaluation data are ready.
