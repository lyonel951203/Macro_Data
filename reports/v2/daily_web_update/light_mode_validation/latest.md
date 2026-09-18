# Daily official-source update - 2026-09-17T10:43:17.763298+08:00

Overall: **SUCCESS**. Wind is excluded.

| Source | Status | Discovered | Baseline skipped | Carried pending | Deferred | Selected | Inserted | Revisions | Unchanged | Parse errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| OECD | SUCCESS_NO_CHANGE | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 32 | 0 |

Each run archives official index/release/API-response bytes and uses append-only, idempotent ingestion. Parser failures remain pending in durable state and are retried even after their URL leaves the current index.
