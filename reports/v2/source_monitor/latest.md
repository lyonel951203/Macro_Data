# 多来源拉取监控 — 2026-09-14T15:07:42.768158+08:00

| 来源 | 状态 | PID/存活 | 完成/队列 | 正文归档 | 目录归档 | 待审正文 | 入库 | 今日请求/上限 |
|---|---|---|---|---:|---:|---:|---:|---|
| NBS | QUEUE_DRAINED_WITH_REVIEW_PENDING | 3332 / 否 | 174/174 search_windows | 1068 | - | 1050 | 322 | 0/不限 |
| PBOC | QUEUE_COMPLETE_WITH_BLOCKED_ROUTES | 21584 / 否 | 363/363 urls | 214 | 147 | 214 | 0 | 0/不限 |
| SAFE | RAW_QUEUE_COMPLETE_REVIEW_PENDING | 12032 / 否 | 383/383 urls | 319 | 64 | 319 | 0 | 0/不限 |

NBS 的队列单位是检索窗口；其余来源是 URL，分母可能随已核目录发现新链接而增加。原稿归档与 PIT 入库分开计数。

- **NBS**：2022-10-01 至 2022-12-31：经济运行；心跳 2026-09-11T12:50:21.737219+08:00；原始状态 `QUEUE_DRAINED_WITH_REVIEW_PENDING`。
  请求间隔 75—105 秒；单次上限 不限；截止 2026-09-18T09:02:46.163614+08:00。
- **PBOC**：MOF 2026 金融运行 page 1；心跳 2026-09-09T18:25:05.895301+08:00；原始状态 `QUEUE_COMPLETE_WITH_BLOCKED_ROUTES`。
  请求间隔 45—65 秒；单次上限 不限；截止 2026-09-16T08:51:28.509371+08:00。
  受阻站点：{"www.pbc.gov.cn": "robots.txt disallows this URL: https://www.pbc.gov.cn/english/130730/3660709/3660738/2025080815062175244/index.html", "gxt.hunan.gov.cn": "cannot verify robots.txt for https://gxt.hunan.gov.cn; crawl stopped"}
- **SAFE**：国家外汇管理局公布2026年7月银行结售汇和银行代客涉外收付款数据；心跳 2026-09-09T15:27:24.782190+08:00；原始状态 `RAW_QUEUE_COMPLETE_REVIEW_PENDING`。
  请求间隔 45—65 秒；单次上限 不限；截止 2026-09-16T08:51:28.511941+08:00。

PBOC/SAFE 当前只归档、不写主库。NBS 等待额度时进程仍可存活；SOURCE_BLOCKED 和队列完成均不代表数据已完整。
此文件由监控进程定时刷新；若顶部时间不再变化，请运行监控脚本重新核对进程。
