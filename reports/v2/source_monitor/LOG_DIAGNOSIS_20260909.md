# 后台日志核查（2026-09-09 09:12）

受阻集中在 PBOC 的两个入口。NBS 为程序预算等待；SAFE 持续成功下载。本次核查未发现所检查 stderr 中有 Python 异常堆栈，未重试受阻入口或调整运行额度。

| 任务/入口 | 实际日志 | 判断与影响 |
|---|---|---|
| NBS，PID 24500 存活 | `NBS per-run request budget exhausted (300)`；心跳持续更新 | 项目每轮额度耗尽，按当前代码等待 9/10。今天账本 184/400，没有证据表明站点封锁 |
| PBOC 原站 | robots 请求 HTTP 200，随后 `robots.txt disallows this URL` | robots 明确禁止该英文原稿路径，任务停止请求该站点 |
| 湖南政府转载 | 请求 `https://gxt.hunan.gov.cn/robots.txt` 时 `ConnectError: [SSL: BAD_ECPOINT] bad ecpoint (_ssl.c:1006)`，HTTP 状态为空 | TLS 连接失败，未能读取 robots。上层显示 `cannot verify robots.txt`；不能据此认定该站点 robots 明确禁止。仅凭此日志不能确定是服务端还是本地 TLS 兼容问题 |
| 财政部转载 | robots 返回 404；两篇正文随后均 HTTP 200 | 现有客户端将 robots 404 视为没有规则文件并继续；两篇原稿成功归档，这个 404 没有阻断正文拉取 |
| SAFE，PID 28640 存活 | 最近三篇正文 HTTP 200，心跳和队列持续前进 | 正常运行；09:12 快照为 19 篇正文、4 页目录，当前推进至 2011 年 |

PBOC 四个种子已处理结束：两条入口受阻、两篇财政部转载已归档；状态 `QUEUE_COMPLETE_WITH_BLOCKED_ROUTES`，进程正常结束。这不是等待后就会自动继续的历史队列，也不表示央行历史拉全。继续推进需要补充可访问来源/队列，或查明湖南入口的 TLS 兼容问题，再重新评估该路径。

目前三项后台任务新增严格观测均为 0；归档成功与可用 PIT 数据入库仍分开计数。既有 B01 的 12 条不计入本轮后台新增。

证据：

- `data/history_backfill/source_workers/pboc/crawl_events.jsonl`：各入口的底层状态、连接错误与成功原稿。
- `data/history_backfill/source_workers/safe/crawl_events.jsonl`：连续成功下载事件。
- `data/history_backfill/pit_history_autorun.json`：NBS 预算等待状态。
- `src/macro_pit/http.py` 中 `_assert_robots_allowed`：robots 404 和无法核验时的分支。
- [实时监控](latest.md)：进程存活、心跳、来源队列和额度；本文数值为 09:12 快照。
