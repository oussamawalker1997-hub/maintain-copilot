# Verification record — v0.1

Observed locally on 26 October 2026, Python 3.12.14 / Linux. These are development results, not customer or production outcomes.

| Check | Observed result | Scope / limit |
|---|---|---|
| `python -m pytest -q` | 28 passed after UTF-8 correction | API, access, variants, lifecycle, concurrency, tickets, backup, encoding repair |
| `python -m ruff check .` | Passed | Static lint |
| `python -m ruff format --check .` | Passed | Python formatting |
| `node --check src/maintain/web/app.js` | Passed | JavaScript syntax only |
| `python scripts/evaluate.py` | 10/10 public smoke cases passed | Known synthetic fixtures, not independent final evaluation |
| `python scripts/verify_live.py` | Passed | Real loopback HTTP: UI files, schema, sources, ticket and dispatch |
| Editable package installation | Passed | Installed into an isolated venv |
| Browser rendering and interaction | User screenshots confirm login, asset selection, search and source page | Source mojibake found on Windows; repair awaiting user verification |
| Windows installation | User confirmed Python 3.12.4, installation, pip check and Ruff | User's own Windows machine |
| Windows pytest after permission correction | User confirmed 25 passed | Expanded encoding suite Windows rerun pending |
| Docker build/runtime | Not executed | Docker unavailable |
| GitHub Actions | Workflow prepared, not executed remotely | Account connection required |
| Business impact / industrial safety | Not measured / not validated | No actual enterprise pilot |

The dependency combination emits a Starlette warning about the future replacement of HTTPX TestClient support. Current tests pass with the pinned versions. Do not hide this warning; review the migration before updating the lockfile. The HTTP server check uses the standard library and is independent of TestClient.

Windows portability correction: retain the full restore/search test on every platform, but assert POSIX mode bits only when `os.name == "posix"`. This does not validate Windows ACLs or claim equivalent file protection there. The GitHub workflow now includes both Linux and Windows runners; their remote results remain unverified until publication.

Two defects found during development: a SQLite connection could be entered and exited on different FastAPI worker threads; fixed with request-owned connections allowing sequential cross-thread use. An empty upload test accidentally reused the deliberately quarantined fixture with different metadata; the 409 was correct, and the test now uses distinct content. Concurrency and duplicate-metadata tests retain these behaviors.

The mission's 200-case final set, 80-case development set, large-volume load targets and 30-day SLO are not met by this small smoke suite. Synthetic document pages are short; whole-page retrieval is a baseline, not the target chunking approach. Plaintext source storage, synchronous extraction and single-process limits remain documented prototype constraints.

GitHub Actions major references were checked against the official action READMEs on 26 October 2026:

- https://github.com/actions/setup-python/blob/main/README.md
- https://github.com/actions/upload-artifact

UTF-8 correction: all project text readers specify their encoding. A regression test simulates a CP1252 default reader and verifies exact French/German characters. The repair script takes an integrity-checked backup, refuses custom content, repairs known fixtures, rebuilds FTS and preserves IDs and credentials. Historical runs remain unchanged; run new searches. Additional tests cover idempotent repair and refusal of custom content.

## User-observed local acceptance, 26 October 2026

User screenshots confirm correct French/German rendering after repair, current and old hardware variant filtering, unknown-code abstention, clarification for a missing firmware, and creation of a confirmed pending ticket. A user-provided read-only database query confirmed that ticket as `sent` with one simulated work order and a `SIM-` reference. A subsequent dispatch returned zero deliveries. These observations cover synthetic fixtures on the user’s Windows machine; they do not constitute an enterprise pilot or a complete authorization audit. Repeated-click idempotence on the UI is not independently confirmed by a screenshot; automated concurrency tests cover the underlying API.
