# Daily macro update - 2026-09-17T22:25:08.531877+08:00

Overall: **PARTIAL**. Wind is excluded; reviewed third-party fallbacks remain PIT_D.

| Source | Status | Discovered | Baseline skipped | Carried pending | Deferred | Selected | Inserted | Revisions | Unchanged | Parse errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NBS | SUCCESS | 16 | 0 | 1 | 2 | 5 | 4 | 2 | 16 | 0 |
| PBOC | BLOCKED_POLICY | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| PBOC_MIRROR | SUCCESS | 5 | 0 | 0 | 0 | 1 | 0 | 0 | 10 | 0 |
| MOF | SUCCESS | 16 | 0 | 0 | 0 | 1 | 0 | 0 | 7 | 0 |
| SAFE | SUCCESS | 14 | 0 | 0 | 2 | 1 | 0 | 0 | 6 | 0 |
| EASTMONEY_MACRO | SUCCESS_NO_CHANGE | 8 | 0 | 0 | 0 | 8 | 0 | 0 | 33 | 0 |
| SINA_MACRO | FAILED | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| OECD | SUCCESS_NO_CHANGE | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 |

Each run archives source response bytes and uses append-only, idempotent ingestion. Parser failures remain pending in durable state and are retried even after their URL leaves the current index.

## SINA_MACRO errors
- CrawlSafetyError: SINA_MACRO daily request budget exhausted (20)

## 运行后修复

22:57已修复本次NBS答记者问误解析：撤回该答记者问页面产生的4条版本（2条错误值、2条重复元数据），恢复NBS主发布页A级值；制造业投资为-2.3%，PPI为3.8%。解析器、异常拦截和备用源额度降级均已更新，260项测试通过。详见 `repairs/20260917_NBS_QA_REPAIR.md`。


