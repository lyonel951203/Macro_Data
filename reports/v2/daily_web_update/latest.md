# Daily macro update - 2026-09-20T22:20:36.088278+08:00

Overall: **PARTIAL**. Wind is excluded; reviewed third-party fallbacks remain PIT_D.

| Source | Status | Discovered | Baseline skipped | Carried pending | Deferred | Selected | Inserted | Revisions | Unchanged | Parse errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NBS | SUCCESS | 15 | 0 | 1 | 2 | 1 | 0 | 0 | 1 | 0 |
| PBOC | BLOCKED_POLICY | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| PBOC_MIRROR | SUCCESS | 5 | 0 | 0 | 0 | 1 | 0 | 0 | 10 | 0 |
| MOF | SUCCESS | 17 | 0 | 0 | 0 | 1 | 0 | 0 | 7 | 0 |
| SAFE | SUCCESS | 14 | 0 | 0 | 2 | 1 | 0 | 0 | 6 | 0 |
| EASTMONEY_MACRO | SUCCESS_NO_CHANGE | 8 | 0 | 0 | 0 | 8 | 0 | 0 | 33 | 0 |
| SINA_MACRO | SUCCESS_NO_CHANGE | 8 | 0 | 0 | 0 | 8 | 0 | 0 | 47 | 0 |
| OECD | FAILED | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Each run archives source response bytes and uses append-only, idempotent ingestion. Parser failures remain pending in durable state and are retried even after their URL leaves the current index.

## OECD errors
- oecd_china_core.yml: CrawlSafetyError: cannot verify robots.txt for https://sdmx.oecd.org; crawl stopped

## DeepSeek semantic audit

Status: **REVIEW_REQUIRED**; candidates: 0 / 0; API called: yes.

Report: `E:\Macro_Data\reports\v2\deepseek_daily_audit\china\latest.md`

## Email delivery

Status: **SENT**; recipient: 718711226@qq.com.
