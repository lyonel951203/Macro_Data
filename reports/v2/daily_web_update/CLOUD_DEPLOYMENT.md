# Macro_Data 官方来源每日更新：云服务器部署与 Agent 交接

更新日期：2026-09-16  
适用项目：`Macro_Data`  
目标：在云服务器上每天无人值守抓取 NBS、PBOC、MOF、SAFE 官方网页，查询 OECD 中国及11国官方 SDMX 修订 API，并检查费城联储 RTDSM 的15个官方 vintage 工作簿；归档响应、解析并幂等写入 `macro_pit_v2.duckdb`。本任务明确不调用 Wind。

## 一、接手时必须保持的规则

1. 只访问 `config/sources.yml` 中允许的官方域名，继续遵守 robots.txt、来源限速、重试上限和熔断规则。
2. 不使用代理轮换、验证码绕过、浏览器指纹伪装或广泛并发抓取。
3. 同一数据库同时只能有一个写入进程。不要让本地Windows任务和云端任务共同写同一个数据库文件。
4. `observation_vintage` 只追加，不覆盖旧版本。相同记录重复运行是 no-op；值变化保存新 vintage。
5. 同一官方URL后来改值时，修订版的 `available_at` 使用本次首次观察时间，标记为 `official_web_revision_first_seen`；不得倒填至原页面发布日期。
6. OECD使用官方 `EDITION` 月份构造PIT_B版本：版本月末记为 `release_at`，次日记为 `available_at`；每日重取完整筛选结果，旧值变化保留为新vintage。
7. RTDSM使用官方vintage日期构造PIT_B版本：日期次日才进入 `available_at`；每日重取15个工作簿，保留历史修订。
8. 单一来源或单一清单失败不能阻止其他来源。PBOC被robots策略阻止时只记录失败，不尝试绕过。
9. 原稿、API响应、抓取日志、运行回执和状态文件都属于数据资产，不能只迁移DuckDB。

## 二、现有入口与状态文件

- 主运行器：`scripts/run_daily_web_update.py`
- 中国配置：`config/daily_web_update.yml`
- 国外配置：`config/daily_global_update.yml`
- NBS目录：`config/daily_nbs_index_urls.txt`
- MOF每日目录：`config/daily_mof_index_urls.txt`
- SAFE目录：`config/daily_safe_index_urls.txt`
- OECD任务清单：`config/oecd_china_core.yml`、`config/oecd_core_part1.yml`、`config/oecd_core_part2.yml`
- RTDSM任务清单：`config/rtdsm_core.yml`
- 本地Windows入口：`run_daily_web_update.cmd`、`run_daily_global_update.cmd`
- 中国持久状态：`data/daily_web_update/state.json`
- 国外持久状态：`data/daily_global_update/state.json`
- 共享互斥锁：`data/daily_web_update/run.lock`
- 每次运行回执：`reports/v2/daily_web_update/runs/*.json`、`reports/v2/daily_global_update/runs/*.json`
- 最新机器可读状态：`reports/v2/daily_web_update/latest.json`
- 最新可读状态：`reports/v2/daily_web_update/latest.md`
- 来源日汇总：`logs/daily_web_update/update_YYYYMMDD.json`
- Windows持续输出：`logs/daily_web_update/launcher.log`
- 请求级审计：DuckDB表 `crawl_log`
- 原始证据：`data/raw/`

当前Windows有两个计划任务：`Macro_Data_Daily_Web_Update`每天22:00运行中国来源，`Macro_Data_Daily_Global_Update`每天00:00运行OECD、RTDSM、ChinaBond和IMF。二者共享数据库写入锁；国外任务最多等待3小时。Windows任务启用StartWhenAvailable和WakeToRun；完全关机仍无法被任务唤醒。云端正式接管前必须先停用本地两个任务。

## 三、补跑语义与限制

Windows的 `StartWhenAvailable` 和Linux systemd的 `Persistent=true` 都只会在恢复后补执行一次，不会为每个错过的自然日分别运行一次。项目通过“目录回溯＋持久待处理队列”补足这一点：

- NBS每次检查当前发布目录、前两页历史目录和综合发布目录。
- MOF每次检查当前财政收支目录和前一页；首次接入把既有链接设为基线，只复查最新3篇，不清理历史缺口。
- SAFE每次检查当前统计数据页、当前解读页和解读前一页。
- 本次目录发现的所有URL先写入状态；单轮最多处理20个，剩余URL以后继续排队。
- 已经发现但解析失败的URL保存在 `state.json`，即使退出当前目录页也继续重试。
- 已成功页面中的最新3个每天复查，用于发现官网同页修订。
- OECD每次重取中国及11国过滤后的完整修订数据集，RTDSM每次重取15个完整vintage工作簿，ChinaBond复查最近75天，IMF重取当前历史工作簿；停机期间出现的新观测或新版本可在恢复后补入。
- 入库是幂等的，因此崩溃后重跑不会重复写入已完成记录。

以下情况不能宣称自动完整补齐：

- 停机时间长到新发布已经翻出配置的目录回溯范围，并且此前从未被本任务发现；
- PBOC目录或正文被robots.txt禁止；
- 官网改变目录HTML、正文格式、链接规则或单位，导致发现器/解析器失败；
- 单次新增超过20个时，虽然已发现URL会排队，但清空积压需要多次运行；
- 官方只更新附件而目录链接和解析规则无法识别附件变化。

出现上述情况，云端Agent应先查看回执和原稿，扩大经过核验的目录页清单或修复解析器，再重跑。不得把“进程正常结束”解释为“数据完整”。

## 四、服务器要求

推荐Linux服务器：

- Python 3.11；
- 4 GB以上内存；
- 数据盘至少预留现有项目数据量的3倍，用于原稿增长、DuckDB备份和迁移临时文件；
- 稳定出站HTTPS/HTTP；
- 系统时钟启用NTP；
- 不需要Wind、浏览器或桌面环境；
- 建议使用独立系统用户 `macrodata`；
- 项目目录示例：`/opt/macro_data`。

应用内部时间使用Asia/Shanghai。服务器可以保持UTC，但systemd定时器必须明确使用Asia/Shanghai。

## 五、迁移哪些内容

Git仓库没有包含大型数据目录，因此仅克隆代码是不完整的。至少迁移：

1. `macro_pit_v2.duckdb`
2. `data/raw/`
3. `data/daily_web_update/state.json`与`data/daily_global_update/state.json`（首次运行后存在）
4. `reports/v2/pit_work_step2_estimated_availability/estimated_available_v1.csv`
5. `config/`
6. 源代码、脚本、测试和 `pyproject.toml`
7. 建议同时迁移 `reports/v2/daily_web_update/` 与 `logs/daily_web_update/` 以保留运行历史。

`data/exports/` 可重新生成，不是强制迁移项。迁移前应停止所有写入者，再复制DuckDB和原稿。复制后分别计算SHA-256；数据库源端和云端哈希必须一致。

本地切换步骤：

```powershell
Disable-ScheduledTask -TaskName Macro_Data_Daily_Web_Update
Disable-ScheduledTask -TaskName Macro_Data_Daily_Global_Update
Get-ScheduledTask -TaskName Macro_Data_Daily_Web_Update,Macro_Data_Daily_Global_Update
```

确认状态为Disabled且没有 `run_daily_web_update.py` 进程后，再执行最后一次数据同步。云端验收完成后，可以保留已禁用的本地任务作为回退入口；不要同时启用两端。

## 六、Linux安装

以下命令由云服务器Agent根据实际用户名和目录调整：

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin macrodata
sudo mkdir -p /opt/macro_data
sudo chown -R macrodata:macrodata /opt/macro_data
```

把代码和上述数据资产放入 `/opt/macro_data` 后：

```bash
cd /opt/macro_data
sudo -u macrodata python3.11 -m venv .venv
sudo -u macrodata .venv/bin/python -m pip install --upgrade pip
sudo -u macrodata .venv/bin/python -m pip install -e .
sudo -u macrodata env PYTHONPATH=/opt/macro_data/src \
  .venv/bin/python scripts/run_daily_web_update.py --config config/daily_web_update.yml --dry-run
sudo -u macrodata env PYTHONPATH=/opt/macro_data/src \
  .venv/bin/python scripts/run_daily_web_update.py --config config/daily_global_update.yml --dry-run
sudo -u macrodata .venv/bin/python -m pytest \
  tests/test_daily_web_update.py tests/test_work_mode.py \
  tests/test_db_contracts.py tests/test_pit.py tests/test_cli.py tests/test_oecd.py tests/test_rtdsm.py -q
```

离线演练必须显示：

- `wind_included: false`
- 来源只有 `NBS`、`PBOC`、`MOF`、`SAFE`、`OECD`、`RTDSM`
- 所有目录URL为预期官方域名
- NBS包含当前页和 `index_1.html`、`index_2.html`
- MOF显示当前页、`index_1.htm` 及 `bootstrap_existing_as_baseline: true`
- SAFE包含当前页和 `index_2.html`
- OECD显示 `official_sdmx_revisions_api` 模式及中国、全球part1、全球part2三个清单
- RTDSM显示 `official_rtdsm_vintage_workbooks` 模式及 `config/rtdsm_core.yml`

## 七、systemd服务与定时器

云端也拆成两个oneshot服务，并共用项目锁。创建`macro-data-china.service`：

```ini
[Unit]
Description=Macro_Data China official-source update
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=macrodata
Group=macrodata
WorkingDirectory=/opt/macro_data
Environment=PYTHONPATH=/opt/macro_data/src
Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Shanghai
ExecStart=/opt/macro_data/.venv/bin/python -u /opt/macro_data/scripts/run_daily_web_update.py --config /opt/macro_data/config/daily_web_update.yml --allow-network
TimeoutStartSec=4h
UMask=0027
Nice=10
NoNewPrivileges=true
PrivateTmp=true
```

创建`macro-data-global.service`，国外任务最多等待中国任务3小时：

```ini
[Unit]
Description=Macro_Data non-China OECD and RTDSM update
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=macrodata
Group=macrodata
WorkingDirectory=/opt/macro_data
Environment=PYTHONPATH=/opt/macro_data/src
Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Shanghai
ExecStart=/opt/macro_data/.venv/bin/python -u /opt/macro_data/scripts/run_daily_web_update.py --config /opt/macro_data/config/daily_global_update.yml --allow-network --lock-wait-seconds 10800
TimeoutStartSec=5h
UMask=0027
Nice=10
NoNewPrivileges=true
PrivateTmp=true
```

分别创建22:00和00:00定时器，均设置`Persistent=true`和`RandomizedDelaySec=5m`：

```ini
# /etc/systemd/system/macro-data-china.timer
[Unit]
Description=Run Macro_Data China update daily
[Timer]
OnCalendar=*-*-* 22:00:00 Asia/Shanghai
Persistent=true
RandomizedDelaySec=5m
Unit=macro-data-china.service
[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/macro-data-global.timer
[Unit]
Description=Run Macro_Data global update daily
[Timer]
OnCalendar=*-*-* 00:00:00 Asia/Shanghai
Persistent=true
RandomizedDelaySec=5m
Unit=macro-data-global.service
[Install]
WantedBy=timers.target
```

执行：

```bash
sudo systemd-analyze verify /etc/systemd/system/macro-data-{china,global}.{service,timer}
sudo systemctl daemon-reload
sudo systemctl enable --now macro-data-china.timer macro-data-global.timer
systemctl list-timers 'macro-data-*'
```

## 八、首次在线验收

不要直接把“定时器已启动”当作上线完成。云端Agent应执行一次受控在线验收：

```bash
sudo systemctl start macro-data-china.service
sudo systemctl start macro-data-global.service
sudo systemctl status macro-data-china.service macro-data-global.service --no-pager
sudo journalctl -u macro-data-china.service -u macro-data-global.service -n 500 --no-pager
```

随后检查：

```bash
cat reports/v2/daily_web_update/latest.md
python -c "import json;print(json.load(open('reports/v2/daily_web_update/latest.json',encoding='utf-8'))['status'])"
```

验收条件：

1. 六个来源均产生明确状态；某一来源或一个版本清单失败时其他来源仍有回执。
2. `latest.json`、`latest.md` 和 `runs/<run_id>.json` 已生成。
3. `data/daily_web_update/state.json` 已保存发现URL和成功/失败状态。
4. `data/raw/` 有对应目录页/正文原稿，数据库 `crawl_log` 有请求记录。
5. 新记录的 `available_at` 不晚于其首次可见时点；官网同页修订不得倒填。
6. 重跑一次后相同记录主要计入 `unchanged`，数据库没有重复签名。
7. PBOC若因robots失败，回执必须明确显示原因，不得更换隐蔽抓取方式。
8. `wind_included` 始终为 `false`。

首次在线运行可能因来源限速和OECD全量修订响应持续较长时间。本地实测全球OECD加RTDSM约36分钟、OECD原始响应约0.5GB；不要为了缩短验收而降低间隔或并发同一来源。内容按SHA-256归档，完全相同的响应不会重复占用同等磁盘。

## 九、日志、告警和日常检查

Linux标准输出由journal保存：

```bash
journalctl -u macro-data-china.service -u macro-data-global.service --since '2 days ago'
systemctl status macro-data-china.timer macro-data-global.timer --no-pager
```

项目内的持久证据：

- `reports/v2/daily_web_update/latest.json`与`reports/v2/daily_global_update/latest.json`：监控系统首选；
- 两个报告目录的`latest.md`：人工查看；
- 两个报告目录的`runs/*.json`：每次不可覆盖回执；
- `logs/daily_web_update/`与`logs/daily_global_update/`：来源日志；
- `data/daily_web_update/state.json`与`data/daily_global_update/state.json`：补跑状态；
- `crawl_log`：每个HTTP请求；
- `data/raw/`：原始字节和SHA证据。

建议云端监控在以下情况报警：

- `latest.json` 超过30小时未更新；
- 总状态为 `FAILED` 或 `PARTIAL`；
- 任一来源连续3次失败；
- `DISCOVERY_EMPTY`；
- parser errors连续存在；
- 锁文件存在但PID已死亡；
- 磁盘可用空间低于项目当前占用量的2倍；
- DuckDB无法打开或出现写锁冲突。

`PARTIAL` 并不代表全部失败；应读取每个来源的状态。PBOC robots问题可以长期存在，但仍应持续显示并单独跟踪。

## 十、备份与恢复

DuckDB备份必须在没有写入进程时进行。推荐流程：

```bash
sudo systemctl stop macro-data-china.service macro-data-global.service
test ! -e data/daily_web_update/run.lock
cp --reflink=auto macro_pit_v2.duckdb data/backups/macro_pit_v2_$(date +%Y%m%d_%H%M%S).duckdb
sha256sum macro_pit_v2.duckdb data/backups/macro_pit_v2_*.duckdb
```

原稿目录和状态文件也需要增量备份。恢复时同时恢复数据库、`data/raw/`、`data/daily_web_update/state.json`和`data/daily_global_update/state.json`；只恢复数据库会丢失自动重试水位和原始证据路径。

## 十一、升级与回滚

升级代码前：

1. 等待当前任务结束；
2. 备份DuckDB、状态和最新回执；
3. 更新代码；
4. 运行离线演练和测试；
5. 手动运行一次服务；
6. 验收后保留新版本。

回滚代码不应回滚已经追加的合法vintage。只有在确认数据库损坏时才恢复数据库备份，并记录丢弃了哪些运行回执。

## 十二、给云服务器 Agent 的接手任务

云端Agent应按以下顺序执行，不能跳过验收：

1. 读取本文件、`reports/v2/STATUS.md`、`config/daily_web_update.yml`、`config/daily_global_update.yml`和`config/sources.yml`。
2. 核对服务器操作系统、Python 3.11、时区、磁盘和网络。
3. 确认本地Windows计划任务已禁用，再完成最后一次数据库、原稿和状态同步。
4. 校验源端与云端数据库SHA-256。
5. 创建虚拟环境并安装项目。
6. 执行 `--dry-run` 和相关测试；失败时先修复，不启用定时器。
7. 安装systemd service/timer，确认22:00、00:00 Asia/Shanghai和Persistent=true。
8. 手动启动一次在线任务并检查全部日志、原稿、crawl_log和入库统计。
9. 重跑验证幂等性和修订时点。
10. 将服务器路径、timer状态、首次运行ID、数据库行数变化、来源错误及下一步写入 `reports/v2/daily_web_update/CLOUD_ACCEPTANCE.md`。
11. 只有验收通过后才宣布云端接管完成；PBOC受阻必须作为已知限制单独列出。

若服务器不是Linux，保留相同运行器、状态、日志和验收要求，仅将systemd替换为该平台的单实例持久定时服务。

## 2026-09-17 调度更新

云端部署需同时复制 `config/weekly_web_revision.yml`、`config/weekly_global_revision.yml`，并创建两个附加service/timer：周日02:00运行中国周复核，周日04:00运行全球周复核。每日OECD使用18个月滚动窗口，周任务使用完整历史；RTDSM/IMF每日条件获取，周任务完整解析。四个service必须共用 `data/daily_web_update/run.lock`。

失败URL的 `failure_count` 和 `next_retry_at` 位于现有持久状态文件中：普通失败按1、3、7天退避，404冷却30天。PBOC每日标记 `BLOCKED_POLICY`，只在中国周任务中探测robots策略。Windows及云端文件、验证和迁移清单见 `LIGHT_WEEKLY_SCHEDULE.md`。

## PBOC政府转载网络要求

中国每日/每周配置已包含PBOC_MIRROR，无需新增timer。云服务器需允许只读HTTPS访问
jrj.sh.gov.cn、jr.jl.gov.cn、jrb.qingdao.gov.cn。央行官网继续遵守BLOCKED_POLICY；
不要用Selenium、代理或浏览器指纹绕过其robots策略。三个转载站点独立运行，单站失败会写入
回执和持久状态，不能阻断同一期已由其他政府转载验证的数据。
## Sina and Eastmoney fallback network requirements

The existing 22:00 China service also needs read-only HTTPS access to `quotes.sina.cn` and `datacenter-web.eastmoney.com`. No browser, Selenium, login, proxy, or new timer is required. The two adapters make eight serial requests each with configured pacing, archive responses, and assign PIT_D availability from first observation only.


## USTREASURY网络与状态

云服务器需允许只读HTTPS访问 `home.treasury.gov`。`config/daily_global_update.yml` 在每日00:00读取官方收益率XML并复查最近75天；`config/weekly_global_revision.yml` 在周日04:00复查最近400天。历史完成标志保存在 `data/daily_global_update/state.json` 的 `sources.USTREASURY.history_complete`。无需API密钥、浏览器或Selenium。
