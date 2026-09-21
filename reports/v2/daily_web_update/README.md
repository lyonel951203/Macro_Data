# 官方来源每日增量更新

状态日期：2026-09-16。

本地拆分为两个Windows计划任务：

- `Macro_Data_Daily_Web_Update`：每天22:00运行中国来源NBS、PBOC、MOF、SAFE和OECD中国清单。
- `Macro_Data_Daily_Global_Update`：每天00:00运行OECD全球53项、美国RTDSM 15项、ChinaBond三项市场因子和IMF全球商品价格指数。

两个任务不依赖Codex或VS Code。它们共用`data/daily_web_update/run.lock`和同一个DuckDB写入入口，不能并发写库。国外任务配置了最多3小时等待；若22:00中国任务尚未结束，00:00任务等待锁释放后再开始。两个任务均使用`StartWhenAvailable`和`WakeToRun`，同一任务只允许一个实例；中国任务最长4小时，国外任务最长5小时。当前Windows配置要求电脑开机且用户仍处于登录状态，锁屏不影响。

## 数据流

1. 中国任务读取NBS、PBOC、MOF、SAFE官方目录并查询OECD中国SDMX修订清单。
2. 00:00任务依次查询OECD全球part1/part2清单、费城联储15个RTDSM vintage工作簿、ChinaBond最近75天曲线和IMF商品价格工作簿。
3. 原始目录、正文、API响应和工作簿均归档；所有记录通过`insert_observations`幂等追加。
4. 相同记录不重复写入；值变化保存为新vintage，旧版本不覆盖。
5. 单一来源或单一清单失败时继续其余来源，并在各自状态、日志和回执中保留错误。
6. Wind不在任何每日任务中。

PBOC若被robots策略阻止，只记录失败，不绕过限制。ChinaBond仅在robots.txt无法取得时按用户授权继续访问已确认的公开端点；明确Disallow仍会阻断。网页解析失败URL保留在中国任务持久状态中，即使以后退出当前目录也继续重试。OECD每次重取过滤后的完整修订历史，RTDSM每次重取15个完整工作簿，因此多日停机恢复后可以补入期间出现的新观测和修订。

## 中国任务文件（22:00）

- 配置：`config/daily_web_update.yml`
- 入口：`run_daily_web_update.cmd`
- 安装：`scripts/setup/install_daily_web_update_task.ps1`
- 状态：`data/daily_web_update/state.json`
- 回执：`reports/v2/daily_web_update/`
- 日志：`logs/daily_web_update/`
- 查看：`monitor_daily_web_update.cmd`

## 国外任务文件（00:00）

- 配置：`config/daily_global_update.yml`
- 入口：`run_daily_global_update.cmd`
- 安装：`scripts/setup/install_daily_global_update_task.ps1`
- 状态：`data/daily_global_update/state.json`
- 回执：`reports/v2/daily_global_update/`
- 日志：`logs/daily_global_update/`
- 查看：`monitor_daily_global_update.cmd`

两者使用同一运行器：`scripts/run_daily_web_update.py`。

两个CMD通过`scripts/run_with_live_log.py`启动：每条进度同时实时打印到CMD窗口并以UTF-8追加到各自`launcher.log`，子进程退出码原样返回。已运行中的旧进程不会热切换，从下一次启动生效。

离线检查：

```powershell
$env:PYTHONPATH='src'
python scripts/run_daily_web_update.py --config config/daily_web_update.yml --dry-run
python scripts/run_daily_web_update.py --config config/daily_global_update.yml --dry-run
```

移除计划任务：

```powershell
Unregister-ScheduledTask -TaskName Macro_Data_Daily_Web_Update -Confirm:$false
Unregister-ScheduledTask -TaskName Macro_Data_Daily_Global_Update -Confirm:$false
```

## 验收

- 两份干运行分别只包含中国5来源和00:00任务4来源，`wind_included=false`。
- 国外任务使用共享锁并设置`--lock-wait-seconds 10800`。
- 2026-09-16国外真实检查：OECD 36个请求新增1961条，其中修订1914条；澳大利亚零售频率误配已修正为季度并验证4626条、0错误。RTDSM 15/15工作簿成功，108490条不变、0错误。
- 首次国外全量检查约36分钟，OECD网络响应约0.5GB；相同原稿按SHA-256复用。
- 完整测试237项通过；拆分计划、共享锁等待和原有PIT流程均通过。
- 两个计划任务均为Ready；下一次运行分别为2026-09-16 22:00和2026-09-17 00:00。

云服务器迁移与Agent接手步骤见 [CLOUD_DEPLOYMENT.md](CLOUD_DEPLOYMENT.md)。

## 2026-09-17 轻量与周复核拆分

每日任务现已改为轻量模式，并新增周日完整修订核查。失败退避、404冷却、PBOC `BLOCKED_POLICY` 和四项计划任务说明见 [LIGHT_WEEKLY_SCHEDULE.md](LIGHT_WEEKLY_SCHEDULE.md)。

## 2026-09-18 美国财政部收益率

00:00全球每日任务新增 `USTREASURY`，读取美国财政部官方 Daily Treasury Par Yield Curve Rates XML。系统每天复查最近75天，周日04:00任务复查最近400天；首次回补从2005-01开始。主库保存每月最后一个已公布交易日的2年、10年、30年恒定到期收益率。

财政部年度XML只提供观察日期，未提供稳定的精确发布时间。为避免前视，`release_at` 与 `available_at` 均保守记为观察日期次日00:00（America/New_York），PIT等级为B。原始XML逐次归档，变值按新vintage追加。30年期因官方停发历史，从2006-02开始。
