# Daily macro update - 2026-09-21T16:50:32.649874+08:00

Overall: **SUCCESS**. Wind is excluded; reviewed third-party fallbacks remain PIT_D.

| Source | Status | Discovered | Baseline skipped | Carried pending | Deferred | Selected | Inserted | Revisions | Unchanged | Parse errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CUSTOMS | BLOCKED_TRANSPORT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Each run archives source response bytes and uses append-only, idempotent ingestion. Parser failures remain pending in durable state and are retried even after their URL leaves the current index.

## CUSTOMS transport block
- RuntimeError: all independent indexes failed: https://english.customs.gov.cn/statics/report/preliminary.html: CrawlSafetyError: cannot verify robots.txt for https://english.customs.gov.cn; crawl stopped; https://english.customs.gov.cn/statics/report/monthly.html: CrawlSafetyError: cannot verify robots.txt for https://english.customs.gov.cn; crawl stopped

## CUSTOMS index warnings
- https://english.customs.gov.cn/statics/report/preliminary.html: CrawlSafetyError: cannot verify robots.txt for https://english.customs.gov.cn; crawl stopped
- https://english.customs.gov.cn/statics/report/monthly.html: CrawlSafetyError: cannot verify robots.txt for https://english.customs.gov.cn; crawl stopped

## DeepSeek semantic audit

Status: **DISABLED**; candidates: 0 / 0; API called: no.

Report: `E:\Macro_Data\outputs\customs_validation\report\deepseek_audit\latest.md`

## Email delivery

Status: **DISABLED**; recipient: 718711226@qq.com.
