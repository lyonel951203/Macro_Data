# 多来源后台拉取与监控

2026-09-09 已建立并启动三个来源任务及一个只读监控进程。**当前实时状态请看 [latest.md](latest.md)**，或运行下面的监控命令；本文件不把启动时的 PID/状态当作永久状态。

| 来源 | 当前任务范围 | 限速与预算 | 写入位置 |
|---|---|---|---|
| NBS | 保留现有从 2005 年逐年推进的 154 窗口任务 | 75—105 秒；每日及每轮次数不限 | 原有 raw、队列；已有核验流程允许追加主库 |
| PBOC | 财政部官方检索和历史转载；新增 10 篇正文、2005—2026 年 132 个年度关键词检索窗口，自动继续分页 | 基础 45—65 秒；次数不限；财政部正文遵守更慢的 75—105 秒节奏 | 原稿、独立回执与日志；**不写主库** |
| SAFE | 2010/2011 早期原稿及数据解读栏目 64 页，从旧目录向新目录发现目标正文；初始 66 个 URL | 45—65 秒；每日及每轮次数不限 | 原稿、独立回执与日志；**不写主库** |

2026-09-09 按用户要求取消 NBS/PBOC/SAFE 的每日及每轮次数上限，配置值 `null` 表示不限；其他来源配置不变。各来源内部只有一个任务，独立账本继续累计请求次数，监控将旧账本与新账本加总。转载站点共享来源请求间隔。旧预算等待在两项上限均取消后恢复，不清零账本或重试已受阻路径。7 天运行期限及有限队列仍保留。不要同时另开旧 CLI 抓取同一来源；旧入口尚未统一接入新的独立账本和锁。

央行原站英文样本被 robots 禁止、湖南入口 TLS 失败的记录保留，当前新增任务仅请求已验证的财政部来源。中国政府网旧样本实际返回 404。转载保留实际 URL、托管站点和统计来源，不能用抓取时间或 URL 的迁移日期冒充 PIT 发布时间。央行使用独立配置 `config/history/pboc/pboc_reprint_pull.json`，来源切换前实测依据及年度检索规则见 [接入说明](../pboc_reprints/README.md)。队列结束仍不代表央行历史完整。

## 随时查看

1. **在 IDE 中打开 [latest.md](latest.md)**：隐藏监控进程每 10 秒刷新。
2. **双击项目根目录 [monitor_progress.cmd](../../../monitor_progress.cmd)**：每 5 秒输出一次实时进度，按 Ctrl+C 退出窗口；这不会停止下载任务。
3. 在项目根目录使用项目 Python：

```powershell
$env:PYTHONPATH='E:\Macro_Data\src'
$env:PYTHONIOENCODING='utf-8'
& 'C:\Users\71871\AppData\Local\Programs\Python\Python311\python.exe' scripts/monitor_source_progress.py
```

加 `--json` 返回结构化快照；加 `--watch 5` 持续查看。前台持续模式只读取状态，不争用隐藏监控的写报告锁，可以随时打开多个查看窗口。

监控显示：来源、真实进程存活、记录状态、心跳时间、目录/正文归档数、待审数、实际入库数、当前 URL/任务、今日合计请求/上限、受阻站点、错误、截止点和最近宽表导出时间。NBS 的完成分母是检索窗口，其余来源是 URL，不能直接按百分比比较。新发现链接会增加 URL 分母。

> 前台的 `monitor_progress.cmd` 用于持续查看；只有 `--watch 10 --quiet` 的隐藏报告写入模式使用单实例锁，避免两个写入者互相覆盖。

## 文件位置

- 全部来源汇总：`reports/v2/source_monitor/latest.md`、`latest.json`。
- 新来源断点：`data/history_backfill/source_workers/pboc/state.json` 和 `safe/state.json`。
- 原稿：`data/raw/pboc/`、`data/raw/safe/`，逐篇 SHA256 和实际来源 URL 在各自状态文件中。
- 抓取事件：各来源目录内 `crawl_events.jsonl`。只写独立日志，不争用 NBS 的 DuckDB 连接。
- 独立日请求账本：各来源目录内 `budget/YYYY-MM-DD.json`；监控同时加上旧共享账本的用量。
- 进程输出/错误：`reports/v2/source_monitor/logs/`；来源实例注册：`data/history_backfill/source_workers/registry.json`。
- NBS 保持原断点 `data/history_backfill/pit_history_autorun.json`，代码调整后重启会更换 PID，历史计数保留。

## 启停与边界

启动器：`python scripts/start_source_workers.py --sources PBOC SAFE --monitor`。活进程已有锁时复用，不重复启动；发现遗留死锁会报错，需核对原进程后处理。支持 `--sources SAFE` 只启动一个来源；`--sources --monitor` 只启动监控。

平缓停止某来源：创建 `data/history_backfill/source_workers/pboc/stop` 或 `safe/stop` 文件。当前请求和限速结束后在检查点退出。NBS 沿用 `data/history_backfill/pit_history_autorun.stop`。停止隐藏监控用 `data/history_backfill/source_workers/monitor.stop`；只停止监控不影响下载。

PBOC/SAFE 每个任务最长 7 天、最多 1,500 个发现 URL；每日及每轮请求数量不限，重启不清零计数。队列完成或受阻状态不会自动扩展未知来源或修改解析器。新来源此阶段只归档，后续由单独的统一入库流程核验合并；监控会明确显示其入库数为 0。

取消数量上限变更：39 项针对性测试通过，覆盖不限次数仍计账、有限额度仍生效、429 熔断、允许站点检查、跨站点共享计数、旧等待恢复，以及来源和监控原有行为。NBS 解析代码未改动，重启前另执行离线原稿回放。
