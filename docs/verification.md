# Verification record — v0.1

Current evidence updated on 28 October 2026 (Europe/Berlin), Python 3.12.
These are development results, not customer or production outcomes.

The PostgreSQL API implementation passed [GitHub Actions run 40602873724](https://github.com/oussamawalker1997-hub/maintain-copilot/actions/runs/40602873724)
at commit `ccea213a70ab89d2b890f51bd78ac321bae86d59`: all six jobs succeeded,
including the API contract tests, Windows/Linux baselines, and three PostgreSQL credential modes.
The optional API has not yet been accepted on the user's own Windows machine.
Existing SQLite data is not transferred.

| Check | Observed result | Scope / limit |
|---|---|---|
| `python -m pytest -q` | 36 passed, 25 PostgreSQL tests skipped without disposable opt-in | API, access, variants, lifecycle, concurrency, tickets, backup, encoding repair |
| `python -m ruff check .` | Passed | Static lint |
| `python -m ruff format --check .` | Passed | Python formatting |
| `node --check src/maintain/web/app.js` | Passed | JavaScript syntax only |
| `python scripts/evaluate.py` | 10/10 public smoke cases passed | Known synthetic fixtures, not independent final evaluation |
| `python scripts/verify_live.py` | Passed | Real loopback HTTP: UI files, schema, sources, ticket and dispatch |
| Editable package installation | Passed | Installed into an isolated venv |
| Browser rendering and interaction | User screenshots confirm login, asset selection, search and source page | UTF-8 repair confirmed; synthetic SQLite journeys confirmed by user |
| Windows installation | User confirmed Python 3.12.4, installation, pip check and Ruff | User's own Windows machine |
| Windows pytest after encoding correction | User confirmed 28 passed; current CI passes 36 | Local optional PostgreSQL API acceptance pending |
| PostgreSQL Docker runtime | User confirmed healthy PostgreSQL 17 and 13 foundation checks | Application Docker image build remains unverified |
| GitHub Actions | Six jobs passed on the implementation commit linked above | Windows/Linux baseline, PostgreSQL foundation and API |
| PostgreSQL API integration | 25 passed on real PostgreSQL 17 | Shared routes, role isolation, concurrent workers, feedback/audit, deferred commit rollback, outages and provisioning guards |
| PostgreSQL live HTTP/CLI | Passed in CI | Server, UI files, OpenAPI, sources, confirmed ticket and dispatch; disposable fixtures only |
| PostgreSQL foundation on user Windows | Migration applied twice; 13 checks passed | Authentication repaired without deleting the volume; API still on SQLite at that observation |
| Business impact / industrial safety | Not measured / not validated | No actual enterprise pilot |

The dependency combination emits a Starlette warning about the future replacement of HTTPX TestClient support. Current tests pass with the pinned versions. Do not hide this warning; review the migration before updating the lockfile. The HTTP server check uses the standard library and is independent of TestClient.

Windows portability correction: retain the full restore/search test on every platform, but assert POSIX mode bits only when `os.name == "posix"`. This does not validate Windows ACLs or claim equivalent file protection there. The GitHub workflow now includes both Linux and Windows runners; both runner jobs have passed remotely.

Two defects found during development: a SQLite connection could be entered and exited on different FastAPI worker threads; fixed with request-owned connections allowing sequential cross-thread use. An empty upload test accidentally reused the deliberately quarantined fixture with different metadata; the 409 was correct, and the test now uses distinct content. Concurrency and duplicate-metadata tests retain these behaviors.

The mission's 200-case final set, 80-case development set, large-volume load targets and 30-day SLO are not met by this small smoke suite. Synthetic document pages are short; whole-page retrieval is a baseline, not the target chunking approach. Plaintext source storage, synchronous extraction and single-process limits remain documented prototype constraints.

GitHub Actions major references were checked against the official action READMEs on 26 October 2026:

- https://github.com/actions/setup-python/blob/main/README.md
- https://github.com/actions/upload-artifact

UTF-8 correction: all project text readers specify their encoding. A regression test simulates a CP1252 default reader and verifies exact French/German characters. The repair script takes an integrity-checked backup, refuses custom content, repairs known fixtures, rebuilds FTS and preserves IDs and credentials. Historical runs remain unchanged; run new searches. Additional tests cover idempotent repair and refusal of custom content.

## User-observed local acceptance, 26 October 2026

User screenshots confirm correct French/German rendering after repair, current and old hardware variant filtering, unknown-code abstention, clarification for a missing firmware, and creation of a confirmed pending ticket. A user-provided read-only database query confirmed that ticket as `sent` with one simulated work order and a `SIM-` reference. A subsequent dispatch returned zero deliveries. These observations cover synthetic fixtures on the user’s Windows machine; they do not constitute an enterprise pilot or a complete authorization audit. Repeated-click idempotence on the UI is not independently confirmed by a screenshot; automated concurrency tests cover the underlying API.
