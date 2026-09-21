# Daily macro update - 2026-09-20T02:30:16.618098+08:00

Overall: **SUCCESS**. Wind is excluded; reviewed third-party fallbacks remain PIT_D.

| Source | Status | Discovered | Baseline skipped | Carried pending | Deferred | Selected | Inserted | Revisions | Unchanged | Parse errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NBS | SUCCESS | 15 | 0 | 1 | 2 | 3 | 0 | 0 | 3 | 0 |
| PBOC | BLOCKED_POLICY | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| PBOC_MIRROR | SUCCESS | 5 | 0 | 0 | 0 | 3 | 0 | 0 | 30 | 0 |
| MOF | SUCCESS | 17 | 0 | 0 | 0 | 3 | 0 | 0 | 21 | 0 |
| SAFE | SUCCESS | 14 | 0 | 0 | 2 | 3 | 0 | 0 | 13 | 0 |
| OECD | SUCCESS_NO_CHANGE | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 2692 | 0 |

Each run archives source response bytes and uses append-only, idempotent ingestion. Parser failures remain pending in durable state and are retried even after their URL leaves the current index.

## PBOC errors
- CrawlSafetyError: robots.txt disallows this URL: http://www.pbc.gov.cn/diaochatongjisi/116219/116225/index.html

## DeepSeek semantic audit

Status: **REVIEW_REQUIRED**; candidates: 0 / 0; API called: yes.

Report: `E:\Macro_Data\reports\v2\deepseek_weekly_audit\china\latest.md`

## Email delivery

Status: **SENT**; recipient: 718711226@qq.com.
