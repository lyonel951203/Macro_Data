# NBS 检索第 9 页恢复（2026-09-09）

## 故障证据

16:05:55，2014 年“经济运行”第 9 页返回 HTTP 200，但 JSON 为 `ok=false, code=201, msg=无搜索词`。缓存键明确含 `qt=经济运行`，前 8 页已正常完成。故障响应被 HTTP 缓存保存；旧发现流程直接抛出 DataContractError，导致整个 NBS worker 退出，单纯重启仍会读到这份错误缓存。

- 原始错误响应：`data/raw/nbs/2026/09/09/03cdf268365e92ffd575a6b6d25fe19bfd9a49544a53196cdafd8d25dc211a56.json`。
- 原请求缓存、检索断点、worker 断点已分别封存在 `cache_before.json`、`search_before.json`、`worker_before.json`。
- 相同参数实测恢复成功，因此无需更换来源或修改关键词；服务端为何单次返回空检索词尚未确定。

## 修复行为

- 在请求前拒绝空白检索词。
- 仅对明确的 `ok=false/code=201/无搜索词` 响应启用同页刷新重试；原始响应和错误历史保留。
- 重试继续使用统一客户端的限速、robots、预算与 HTTP 熔断；不跳页、不将失败记为空结果或窗口完成。
- 同页失败请求计数写入断点，达到 3 次停止，即使重启也不会重置此计数。未知错误仍停止。
- 相同响应字节被客户端标为缓存命中时，实际联网请求仍计入请求与重试预算。
- 返回有效搜索结果后清理当前错误标志，历史证据保留；worker 的监控错误同步更新。

## 验证

- `pytest tests/test_nbs_search.py tests/test_http_safety.py tests/test_pit_autorun_validation.py -q`：**33 passed**。
- `scripts/verify_nbs_search_recovery.py --allow-network` 使用独立检索断点及独立 probe.duckdb，未推进生产断点或向主库写入观测。
- 初次沙箱联网遇到 WinError 10013，按权限流程在允许联网环境重试，未关闭 robots 或 TLS 校验。
- 实际请求在 **16:26:22** 返回 HTTP 200、20 条结果、总命中 345，测试断点从第 9 页推进至第 10 页，`live_probe.json` 为 PASS。
- 新成功响应：`data/raw/nbs/2026/09/09/1a67e965655faeff72e78df4606ce9ab3eefca93549838cf4b2aa68948a067f2.json`。
- `scripts/check_pit_history_autorun.py` 在 16:27 完成：311 份归档、486 条独立核验、0 不匹配、0 失败，生成与当前代码一致的 PASS 哈希门禁，副本为 `preflight.json`。
- 16:28 恢复隐藏 worker **PID 25796**，从原生产断点读取验证过的第 9 页缓存；16:29 正常获取第 10 页（20 条结果），继续第 11 页。监控旧错误已清除；运行状态与代码哈希见 `recovery.json`，恢复后断点见 `worker_after.json` / `search_after.json`。
- 启动器沿用既有规则，从本次启动起计 7 天，本轮截止 2026-09-16 16:28。每日和每轮请求数量仍不限，单来源限速仍为 75—105 秒。

PBOC、SAFE 任务不在本次修复范围。当前归档数和进程状态以 [实时监控](../source_monitor/latest.md) 为准。
