# API v0.1

All `/v1` endpoints require `Authorization: Bearer <local-key>`. An active principal has one site and one role. IDs are opaque; a foreign-site object returns 404. API schema: `GET /openapi.json`. The local documentation route is a schema landing page; import the OpenAPI JSON into your API client.

| Method | Route | Purpose |
|---|---|---|
| GET | `/healthz` | Readiness and explicit baseline mode |
| GET | `/v1/me` | Current identity, site and role |
| GET | `/v1/assets` | Assets in current site |
| POST | `/v1/answers` | B0 search with applicability and references |
| GET | `/v1/runs/{id}` | Own run after source revalidation |
| GET | `/v1/documents?offset=0&limit=20` | Site documents, bounded pagination |
| POST | `/v1/documents` | Editor-only trusted text or PDF ingestion |
| POST | `/v1/documents/{id}/publish` | Publish reviewed draft, supersede exact range |
| POST | `/v1/documents/{id}/revoke` | Revoke version |
| GET | `/v1/documents/{id}/pages/{number}` | Read accessible page |
| POST | `/v1/tickets` | Confirmed ticket with `Idempotency-Key` header |
| GET | `/v1/tickets/{id}` | Own ticket status |
| POST | `/v1/feedback` | Own run feedback using enumerated reason |
| GET | `/v1/audit?limit=50` | Editor view of site principal events |

Search body:

```json
{"asset_id":"NW-P17","question":"Que signifie E042 ?"}
```

Response `status` is `evidence_found`, `needs_clarification` or `abstained`; mode is always `lexical_baseline`. `sources` contains title, version, family, page, text and document ID. This version intentionally returns no generated claims and has no answer-language promise: source text is returned verbatim.

Ticket body (substitute the actual run ID), header `Idempotency-Key: <stable-key-for-this-payload>`:

```json
{"run_id":"actual-run-id","asset_id":"NW-P17","observations":"Synthetic observation","confirmed":true}
```

Repeated key with same principal and body returns the same ticket. A different body with the same key returns 409. Keys have no automatic expiration in v0.1. Ticket status is `pending`, `sent` to the local simulator, or `blocked` by source/access revalidation. Real remote retries and unknown delivery states are future work, not implemented simulation claims.

Document ingestion body:

```json
{
  "title":"Original test procedure",
  "family":"TEST-OBS",
  "revision":"1",
  "model":"NW-Conveyor-C2",
  "hardware":"rev-B",
  "firmware_min":"2.0",
  "firmware_max":"2.9",
  "pages":["E321: fictional observation for demonstration purposes only."]
}
```

Alternatively omit `pages` and supply `pdf_base64` from a **trusted local** PDF. No file upload UI is included in v0.1. The original PDF binary is not retained; only extracted page text is stored. Page numbering follows the provided page list or PDF physical pages. Blank extraction leads to quarantine. Editor review is an explicit publish action, not an independent dual approval system.

Validation: unknown fields refused; questions ≤4,000 characters; ≤500 pages; text ≤2,000,000 characters; PDFs ≤20 MiB; total request body ≤28,000,000 bytes. Source parser CPU/memory isolation is not provided. Error responses contain code, safe message and trace ID; validation input is not reflected. Rate limit: 60 authenticated API requests/minute/principal, in one process. Body limits apply before authentication parsing. HTTPS, edge connection limits and distributed quotas are pilot requirements.
