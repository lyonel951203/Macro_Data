# Daily macro update - 2026-09-20T04:14:47.970982+08:00

Overall: **PARTIAL**. Wind is excluded; reviewed third-party fallbacks remain PIT_D.

| Source | Status | Discovered | Baseline skipped | Carried pending | Deferred | Selected | Inserted | Revisions | Unchanged | Parse errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| OECD | FAILED | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| RTDSM | FAILED | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| USTREASURY | SUCCESS_NO_CHANGE | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 60 | 0 |

Each run archives source response bytes and uses append-only, idempotent ingestion. Parser failures remain pending in durable state and are retried even after their URL leaves the current index.

## OECD errors
- oecd_core_part1.yml: CrawlSafetyError: OECD daily request budget exhausted (50)
- oecd_core_part2.yml: CrawlSafetyError: cannot verify robots.txt for https://sdmx.oecd.org; crawl stopped

## RTDSM errors
- rtdsm_core.yml: CrawlSafetyError: RTDSM daily request budget exhausted (30)

## DeepSeek semantic audit

Status: **REVIEW_REQUIRED**; candidates: 0 / 0; API called: yes.

Report: `E:\Macro_Data\reports\v2\deepseek_weekly_audit\global\latest.md`

## Email delivery

Status: **SENT**; recipient: 718711226@qq.com.
