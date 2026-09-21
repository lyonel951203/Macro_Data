# 迁移必读：Global Macro PIT 项目交接

> 新电脑上的 Codex 在执行任何修改或网络请求前，必须完整阅读本文件，并先完成“接管检查清单”。

## 1. 项目目标与范围

本项目构建中国和美国宏观数据的 point-in-time（PIT）数据库，主库为：

```text
macro_pit_v2.duckdb
```

当前必需范围只有：

```text
中国（CN）
美国（US）
```

OECD/global 数据是可选扩展，不阻断中国和美国验收。

项目不是普通“最终历史值”数据库。它必须回答：

> 在某个历史时点，当时实际已经发布并可被市场看到的数据是什么？

因此不能为了补齐历史而把后来修订的最终值伪装成当时可得值。

## 2. 迁移时的最新状态

以下是 `2026-09-04 16:55 +08:00` 的快照。状态可能在复制前继续变化；接管后必须重新读取状态文件和数据库。

MOF 历史回填：

```text
status  = WAITING_NEXT_DAY
queue   = 195
success = 78
pending = 117
last_error = 空
```

最近成功处理到财政部 `2019-08-16` 发布的页面。当前批次没有解析失败。`2026-09-04 16:27` 的进程检查没有发现仍存活的 MOF worker；`WAITING_NEXT_DAY` 是最后持久化状态，不等于进程仍在运行。迁移后需要按第 6 节命令从断点续跑。

权威动态状态文件：

```text
data/history_backfill/mof_2005_state.json
```

逐页日志：

```text
logs/mof_history_backfill.jsonl
```

项目规模快照：

```text
约 1.009 GiB
约 935 个文件
```

中国主库快照：

```text
记录数：5,100
已填充 series：47
PIT_A/B 覆盖占比：70.6%
最早 observation period：1993-01
重复 vintage：0
```

本轮数据质量修复前的可恢复数据库备份：

```text
data/backups/macro_pit_v2_pre_oecd_cn_repair_20260904.duckdb
SHA256=7F47A5ED9D3F804508E0B1120525DEAFE8DC946E11B18B53E415FEB294D9AB8E
```

## 3. 复制前必须做的事情

### 3.1 停止旧电脑上的任务

在正在运行 MOF 回填的 PowerShell 窗口按：

```text
Ctrl+C
```

必须等 PowerShell 提示符重新出现后才能复制。状态文件可能仍显示 `RUNNING` 或 `WAITING_NEXT_DAY`，这不影响断点续跑；是否安全停止以原窗口已经返回提示符为准。

不要在 DuckDB 正在写入时复制项目，也不要使用网盘实时同步正在写入的 `macro_pit_v2.duckdb`。

### 3.2 完整复制整个目录

不要只复制数据库。以下内容都必须保留：

```text
macro_pit_v2.duckdb
config/
src/
tests/
data/raw/
data/http_cache/
data/discovery/
data/history_backfill/
data/audit/request_budget/
data/backups/
logs/
reports/
requirements.txt
pyproject.toml
README.md
docs/history/MIGRATION_README.md
```

推荐新电脑仍使用：

```text
D:\Macro_Data
```

例如复制到移动硬盘 `E:` 时，可在旧电脑执行一整行：

```powershell
robocopy 'D:\Macro_Data' 'E:\Macro_Data' /E /COPY:DAT /DCOPY:DAT /R:2 /W:5 /XJ
```

不要使用 `/MIR`，避免误删目标端已有文件。

### 3.3 比较数据库哈希

停止旧进程后，在旧电脑记录：

```powershell
Get-FileHash 'D:\Macro_Data\macro_pit_v2.duckdb' -Algorithm SHA256
```

复制完成后，在新电脑运行同一命令。两边 SHA256 必须一致。

## 4. 新电脑环境初始化

需要 Python 3.11。不要复制旧电脑的 Python 虚拟环境，直接从项目依赖重新安装。

依次执行：

```powershell
Set-Location -LiteralPath 'D:\Macro_Data'
```

```powershell
py -3.11 -m pip install -r .\requirements.txt
```

```powershell
$env:PYTHONPATH = 'D:\Macro_Data\src'
```

基础文件检查：

```powershell
Test-Path .\macro_pit_v2.duckdb
```

```powershell
Test-Path .\data\history_backfill\mof_2005_state.json
```

```powershell
Test-Path .\data\discovery\mof_candidates.parquet
```

三条都应返回 `True`。

当前完整测试基线是：

```text
51 passed
```

验证命令：

```powershell
py -3.11 -m pytest -p no:cacheprovider
```

## 5. 新电脑接管后的只读检查

先读取 MOF 断点，不要立即访问网络：

```powershell
$state = Get-Content .\data\history_backfill\mof_2005_state.json -Raw | ConvertFrom-Json; $state | Select-Object status,queue_size,pending,updated_at,last_error
```

检查最后日志：

```powershell
Get-Content .\logs\mof_history_backfill.jsonl -Tail 10
```

检查当日请求预算：

```powershell
Get-Content ".\data\audit\request_budget\$((Get-Date).ToString('yyyy-MM-dd')).json" -ErrorAction SilentlyContinue
```

如果新旧电脑是同一天迁移，不要在新电脑立即追加网络请求。预算账本会随项目一起复制，但 `--max-network-urls` 是每次会话上限，不会自动扣除同日上一台电脑已经完成的批次。

## 6. 续跑 MOF 的唯一推荐命令

确认旧电脑已经停止，并建议等到下一个自然日上午 10 点，再在新电脑执行以下单行命令：

```powershell
py -3.11 -m macro_pit --db-path .\macro_pit_v2.duckdb history-backfill --source MOF --candidates .\data\discovery\mof_candidates.parquet --start-period 2005-01 --state-path .\data\history_backfill\mof_2005_state.json --log-path .\logs\mof_history_backfill.jsonl --max-network-urls 15 --wait-across-days --resume-hour 10 --allow-network
```

该命令会：

1. 读取已有断点；
2. 跳过成功页面；
3. 仅处理剩余页面；
4. 单线程访问财政部；
5. 每个网络页面间隔约 45–65 秒；
6. 每次会话最多新增访问 15 个页面；
7. 每页完成后原子写入断点；
8. 当批次结束后等待下一自然日上午 10 点。

截至迁移快照，应从约 `pending=117` 继续，而不是从头下载。

不要让新旧两台电脑同时运行同一 MOF 任务，否则会重复访问官网，并形成两个分叉数据库。

## 7. PIT 数据等级，不得混淆

```text
A：原始官方值，并有精确官方发布时间
B：原始官方值，但只有发布日期；保守地从次日 00:00 可用
C：有发布日期，但不能证明原始版本
D：只有当前/最终历史值；从项目首次看到它时才算可用
```

严格查询只允许：

```text
pit_mode=strict -> A、B
```

宽松查询允许：

```text
pit_mode=loose -> A、B、C
```

观测查询允许：

```text
pit_mode=observed -> A、B、C、D
```

不得：

- 把 D 改成 A/B；
- 把后来下载的最终历史值倒填为历史时点已知；
- 用经验滞后生成的数据写回 `observation_vintage.available_at`；
- 覆盖旧 vintage；
- 删除原始文件或请求预算账本。

如果以后实现“代理 PIT”，必须放在独立派生表或独立 Parquet 中，并带 `is_proxy=true`、规则版本和估算可用时间；不能进入严格 PIT 验收。

## 8. 当前各来源状态

### MOF：财政部

- 7 个财政指标；
- 原始公告可形成严格 PIT_A/B；
- 候选页面共 195 个；
- 已定位范围约为 2008-08 至 2026-07；
- 当前正在逐页向历史回填。

### NBS：国家统计局

- 当前已有 21 个指标；
- 严格历史主要集中在 2025 年以后；
- CPI、PPI、GDP、PMI、工业、消费、投资等官方历史值存在，但批量最终历史值只能先标 PIT_D；
- 历史公告目录尚未系统回填；
- `2026-09-04` 对 `data.stats.gov.cn` 的单次 CPI 历史接口探测返回 HTTP 403；客户端已立即停止且没有重试；
- 失败证据记录在 `logs/update_20260904.json`，不要重复运行 `config/history/nbs/nbs_easyquery_cpi_history_probe.txt`；
- 不要仅把 `--source` 改成 NBS 就运行，历史任务配置尚未完成。

### PBOC：中国人民银行

- 当前已有 10 个严格指标，但仅覆盖近期；
- 已整理 2004–2026 年共 23 个年度货币供应量页面：`config/pboc_money_supply_history_2004_2026.txt`；
- 对应解析器已支持 M0/M1/M2 存量表；
- PBOC `robots.txt` 当前同时禁止自动访问统计目录和金融统计新闻稿列表页，不得绕过；
- 可考虑用户用浏览器保存官方页面后离线导入，或从允许访问的原始新闻稿入口获取。

浏览器保存文件的标准离线入口已经实现：

```powershell
py -3.11 -m macro_pit archive-manual --source PBOC --input-dir .\data\manual_inbox\pboc --manifest-output .\config\pboc_manual_inbox_raw.yml
```

```powershell
py -3.11 -m macro_pit --db-path .\macro_pit_v2.duckdb backfill-raw --source PBOC --raw-manifest .\config\pboc_manual_inbox_raw.yml
```

已有两个 PBOC 浏览器文件完成端到端验证，离线复跑结果为 `unchanged=20`。

### SAFE：国家外汇管理局

- 已有 7 个指标；
- 已入库 1,415 条 PIT_D 长历史；
- 已新增 84 条年度汇总 PIT_C 记录，覆盖 2018-01 至 2024-12；
- 外汇储备最早到 1999-12；
- 银行结售汇、跨境收付款最早到 2010-01；
- 外汇储备按 observation period 合并 B/C/D 后，从 1999-12 至 2026-07 共 320 个月，当前缺口为 0；
- 年度表只证明整张汇总表的发布日期，不能证明每月首次发布时间，因此标 PIT_C；
- PIT_C/D 历史不得进入严格快照。

### OECD：中国补充修订历史

- 新增 `CN_OECD_CPI_INDEX`：2,373 个 vintage、402 个数据期，1993-01 至 2026-06；
- 新增 `CN_OECD_INDUSTRIAL_PRODUCTION`：316 个有效 vintage，1999-01 至 2026-05；
- 两个序列使用 OECD edition 月份形成 PIT_B，不使用经验滞后；
- 它们是中国宏观补充来源，不替代验收要求的 NBS 国内来源；
- OECD 中国失业率没有返回数据；STES revision 数据集中中国 GDP 查询为 404；
- 不要运行 `config/history/oecd/oecd_china_gdp_discovery.yml`；
- OECD 零售字段返回巨额水平而非声明的指数，已从主库精确移除 3,739 行；工业指数的一条零值哨兵也已移除；原始 CSV 和抓取日志仍保留，可从上面的备份恢复。

### CUSTOMS：海关总署

- 解析器和安全失败检测已实现；
- 当前观察表仍为 0 条；
- 官网受 WAF、超时或异常响应影响；
- 禁止高频重试、代理轮换、浏览器指纹伪装或验证码绕过；
- 现实方案是用户一次性下载官方 Excel/网页后离线导入。

### US：美国 RTDSM

- 已入库 15 个系列；
- 108,490 条记录；
- 1,500 个抽样单元格匹配率 100%；
- 美国验收当前通过。

## 9. 当前宽表导出

严格 PIT 月末宽表：

```text
data/exports/cn_pit_month_end_2005_20260731_values.parquet
data/exports/cn_pit_month_end_2005_20260731_values.csv
data/exports/cn_pit_month_end_2005_20260731_periods.parquet
data/exports/cn_pit_month_end_2005_20260731_metadata.csv
```

宽表规则：

- 纵轴是自然月末；
- 横轴是 `canonical_series_id`；
- 单元格是该月末 23:59:59 时最新可得的严格 A/B 值；
- `periods.parquet` 记录每个数值对应的数据期；
- 不在首次发布前回填，不用 D 填严格表。

当前严格宽表已经重新生成：259 个自然月末、37 个指标列。2005 年起每个月至少有 2 个非空指标，来自 OECD 中国 CPI 和工业生产 revision history；2019 年以后随 MOF、SAFE、NBS、PBOC 数据加入而逐步增多。MOF 回填继续推进后，必须重新运行 `export-wide` 才能反映新增历史。

重新导出命令：

```powershell
py -3.11 -m macro_pit --db-path .\macro_pit_v2.duckdb export-wide --country CN --pit-mode strict --start-date 2005-01-31 --end-date 2026-07-31 --output-prefix .\data\exports\cn_pit_month_end_2005_20260731
```

## 10. 当前验收状态

`acceptance` 当前预期仍然是 `OVERALL: FAIL`，这不是安装失败。

主要未完成项：

```text
中国必要来源：4/5，缺 CUSTOMS
中国核心指标：14/16，缺出口、进口
中国已填充 series：47/25
中国达到历史深度的 series：15/25
中国 A+B 比率：70.6%，仍低于当前 95% 门槛
```

通过项包括：

```text
无需账号/API key
原始文件可复现率 100%
revision 追加保存
PIT 穿越测试
同日发布时间边界测试
幂等写入
US RTDSM 覆盖和抽样验证
重复 vintage 行为 0
```

运行验收：

```powershell
py -3.11 -m macro_pit --db-path .\macro_pit_v2.duckdb acceptance
```

## 11. 网络安全边界

对中国政务网站必须始终遵守：

- 网络默认关闭，必须显式 `--allow-network`；
- 同一官方域名只有一个运行进程；
- 并发固定为 1；
- 遵守 `robots.txt`；
- 缓存优先；
- 使用短且已审核的 URL 清单；
- 检查当日请求预算；
- 401/403/407/429 立即停机，不重试；
- 不使用代理池、IP轮换、指纹伪装、验证码绕过或广泛自动翻页；
- 不需要 ChromeDriver/Selenium。

已确认的禁止重试项：

```text
NBS data.stats.gov.cn 历史接口：HTTP 403
PBOC 统计目录：robots.txt disallow
PBOC 金融统计新闻稿列表：robots.txt disallow
OECD STES revisions 中国 GDP：HTTP 404（表示该数据集没有此序列，不是临时网络故障）
```

新电脑上的 Codex在没有用户明确许可时，不得扩展到新的网络来源或扩大请求范围。当前迁移许可仅覆盖：恢复已有 MOF 断点任务。

## 12. 路径与脚本注意事项

核心 Python CLI 在项目根目录运行时使用相对路径，可迁移到其他根目录；但以下旧辅助 PowerShell 脚本包含硬编码的 `D:\Macro_Data` 和特定日期，不应在新电脑直接使用：

```text
scripts/run_mof_history_discovery.ps1
scripts/run_mof_history_once.ps1
scripts/run_mof_older_discovery_once.ps1
scripts/run_nbs_history_probe_once.ps1
```

新电脑应使用本文件第 6 节的单行 Python CLI 命令。

当前目录不是 Git 工作树。不要使用 `git reset`、`git checkout` 等命令假定可以恢复文件。

## 13. 新电脑 Codex 接管检查清单

在声明“接管完成”前，必须逐项完成：

1. 已完整阅读 `docs/history/MIGRATION_README.md`；
2. 已确认旧电脑上的 MOF 进程停止；
3. 已确认数据库 SHA256 与旧电脑一致；
4. 已确认主库、raw、cache、discovery、history state 和 logs 均已复制；
5. 已读取最新 MOF state，而不是只相信本文件中的静态数字；
6. 已运行测试并确认结果；
7. 已用只读方式检查数据库行数、来源覆盖和重复键；
8. 已检查当日请求预算；
9. 已确认没有另一个 MOF 进程；
10. 只有在用户允许后，才恢复网络回填。

接管后第一条回复应明确报告：

```text
数据库哈希是否一致
测试通过数
MOF queue/success/pending
当日 MOF 请求预算
是否检测到重复运行进程
中国主库行数和 series 数
OECD 中国 CPI/工业生产行数
SAFE 外储 1999-12 至 2026-07 是否仍为 0 缺口
是否可以安全续跑
```
