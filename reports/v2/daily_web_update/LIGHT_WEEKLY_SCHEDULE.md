# 每日轻量更新与每周修订核查

状态日期：2026-09-17

## 调度

| 任务 | Windows任务名 | 时间（Asia/Shanghai） | 职责 |
|---|---|---|---|
| 中国每日轻量 | `Macro_Data_Daily_Web_Update` | 每日22:00 | 新URL、到期失败项、每源最新1篇；PBOC三处政府转载；OECD中国最近18个月 |
| 全球每日轻量 | `Macro_Data_Daily_Global_Update` | 每日00:00 | OECD最近18个月、RTDSM/IMF条件获取、ChinaBond最近75天 |
| 中国周复核 | `Macro_Data_Weekly_Web_Revision` | 周日02:00 | 每源最新3篇、PBOC政府转载复核、OECD中国完整历史、PBOC官网robots策略探测 |
| 全球周复核 | `Macro_Data_Weekly_Global_Revision` | 周日04:00 | OECD完整历史和15个RTDSM完整工作簿 |

四项任务共用 `data/daily_web_update/run.lock`，不会并发写入 `macro_pit_v2.duckdb`。全球任务最多等待共享锁3小时。全部任务启用 `StartWhenAvailable`、`WakeToRun` 和 `MultipleInstances IgnoreNew`。

## 失败处理

- 普通抓取或解析失败按第1、3、7天重试；后续失败继续使用7天间隔。
- HTTP 404冷却30天，不再每天重复请求。
- 失败URL即使退出当前目录仍保留在持久状态中；只有到达 `next_retry_at` 才重新选择。
- 成功后清除 `failure_count`、`error_kind` 和 `next_retry_at`。
- PBOC官网日任务返回来源状态 `BLOCKED_POLICY`，不发起请求，也不使整批日任务失败；周任务才重新读取robots策略。明确Disallow仍然阻止抓取。独立的 `PBOC_MIRROR` 每日扫描上海、吉林、青岛三个政府转载目录，转载时间强制记为PIT_B；同一期至少一个转载成功时，冗余站点失败只记告警。

## 轻量规则

- NBS、MOF、SAFE：新URL立即处理；成功页面每天只复查最新1篇。MOF每日只读当前目录，周任务再读`index_1.htm`；多个目录相互独立，单个分页临时失败只记告警。
- PBOC_MIRROR：三个政府目录和候选页均独立执行；只接受标题明确为全国金融统计数据报告且完整包含10个核心字段的页面，地方金融报告拒绝入库。
- OECD：中国与全球日任务通过SDMX `startPeriod` 查询最近18个月；周任务不加时间过滤，复查完整修订历史。
- RTDSM、IMF：每日发条件请求；服务器确认内容未变化时跳过工作簿解析和数据库比对。
- 周任务仍完整解析OECD历史结果和RTDSM工作簿，即使缓存内容未变化。
- ChinaBond继续按最近75天查询已闭合月末。

## 文件

- 每日配置：`config/daily_web_update.yml`、`config/daily_global_update.yml`
- 每周配置：`config/weekly_web_revision.yml`、`config/weekly_global_revision.yml`
- 每周入口：`run_weekly_web_revision.cmd`、`run_weekly_global_revision.cmd`
- Windows安装脚本：`scripts/setup/install_weekly_revision_tasks.ps1`
- 每周回执：`reports/v2/weekly_web_revision/`、`reports/v2/weekly_global_revision/`
- 每周日志：`logs/weekly_web_revision/`、`logs/weekly_global_revision/`

## 验证

2026-09-17真实OECD中国轻量验证成功：2个请求、32条近期版本记录、0新增、0修订、0错误，约30秒。验证回执位于 `reports/v2/daily_web_update/light_mode_validation/`。PBOC政府转载真实验证发现5篇、选中3篇、HTTP成功3篇、解析错误0；最终回执为SUCCESS，本轮新增20条、2条修订、18条元数据版本、10条不变。完整测试套件为251项通过。

离线检查：

```powershell
$env:PYTHONPATH='src'
python scripts/run_daily_web_update.py --config config/daily_web_update.yml --dry-run
python scripts/run_daily_web_update.py --config config/daily_global_update.yml --dry-run
python scripts/run_daily_web_update.py --config config/weekly_web_revision.yml --dry-run
python scripts/run_daily_web_update.py --config config/weekly_global_revision.yml --dry-run
```

重新注册周任务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup/install_weekly_revision_tasks.ps1
```

云服务器接手时，应建立相同的四个systemd timer：每日22:00、每日00:00、周日02:00、周日04:00，并让四个service继续共用同一锁文件。完整迁移步骤见 `CLOUD_DEPLOYMENT.md`。
## 2026-09-17 third-party fallback addition

The existing 22:00 China task now polls eight reviewed Eastmoney endpoints and eight reviewed Sina endpoints. Each adapter reads only the newest three periods and writes PIT_D first-seen observations. This does not add a Windows task or timer. Official and Wind records retain priority.


## 2026-09-18 USTREASURY补充

- 全球每日00:00：美国财政部收益率曲线复查最近75天。
- 全球周日04:00：复查最近400天，以发现迟到修订。
- 首次历史回补完成后不会每天重扫2005年以来全部年度。
