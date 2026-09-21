# Global Macro PIT Database — PLAN

## 0. 项目目标

构建一个：

**完全免费、无需账号、无需 API Key、无商业/专有数据后端的宏观 PIT 数据库。**

用途：

- 月频 ETF 行业轮动
- 宏观 regime
- 宏观因子
- 宏观 → 行业收益预测
- 后续机器学习特征库

优先级：

```text
P0 中国
P1 美国
P2 全球主要经济体
P3 全球长尾国家
```

### 当前验收范围（2026-09-03 用户确认）

```text
必验：中国 P0
必验：美国 P1
可选：全球 P2 / P3，不影响最终 OVERALL
```

全球数据仍可作为扩展数据维护和审计，但不属于当前 Definition of Done 的阻断条件。

运行模式：

```text
第一次：
历史全量 backfill

以后：
每日 incremental update

量化使用：
按任意历史 as_of 时间生成 PIT snapshot
```

数据库必须能够回答：

> “在 2021-06-30 15:00，当时市场实际能够看到的宏观数据是什么？”

而不是：

> “现在数据库里记录的 2021 年 6 月数据是什么？”

---

## 1. 强制技术约束

使用：

```text
Python 3.11+
DuckDB
Parquet
requests/httpx
BeautifulSoup/lxml
pandas/polars
pytest
```

尽量不要建立 PostgreSQL 等服务。

整个项目必须：

```text
git clone
pip install -r requirements.txt
python ...
```

即可运行。

### 禁止

不得要求：

```text
Wind
Bloomberg
CEIC
Longbridge
TradingEconomics
Refinitiv
FRED API Key
任何登录账户
任何付费 Token
```

---

## 2. 数据源设计

不要找“一个 API 解决全球”。

采用：

```text
官方源
  ↓
免费 real-time 数据集
  ↓
免费聚合源
```

三级结构。

---

## 2.1 中国 P0

### 国家统计局 NBS

抓取至少：

```text
GDP
工业增加值
服务业生产指数
社会消费品零售总额
固定资产投资
制造业投资
基础设施投资
房地产开发投资
商品房销售
CPI
核心 CPI
PPI
城镇调查失业率
制造业 PMI
非制造业 PMI
综合 PMI
PMI：生产、新订单、新出口订单、原材料库存、从业人员、供应商配送时间
```

同时抓：

```text
历年主要统计信息发布日程
历史新闻稿
历史数据表
```

发布时间优先级：
1. 官方新闻稿实际发布时间
2. 官方文件 metadata
3. 官方发布日程
4. 页面发布日期
5. first_seen_at

### 中国人民银行 PBOC

抓：

```text
M0
M1
M2
人民币贷款余额
新增人民币贷款
人民币存款
社会融资规模增量
社会融资规模存量
社融存量同比
企业债券融资
政府债券融资
人民币贷款社融分项
银行间利率
```

重点抓取：

```text
金融统计数据报告
社会融资规模增量统计数据报告
社会融资规模存量统计数据报告
```

不要只抓央行当前历史 Excel。历史新闻稿是 PIT 数据的主要来源。

### 海关总署

抓：

```text
出口额
进口额
贸易差额
出口同比
进口同比
主要国家/地区出口
主要国家/地区进口
```

至少同时保存人民币口径和美元口径。

### 财政部 MOF

抓：

```text
一般公共预算收入
一般公共预算支出
税收收入
非税收入
政府性基金收入
政府性基金支出
土地出让收入（如可获得）
主要税种
```

### SAFE

抓：

```text
外汇储备
银行结汇
银行售汇
结售汇差额
涉外收付款
货物和服务贸易
```

---

## 3. 美国 P1

不要把美国部分建立在 FRED API 上。

主 PIT 数据源使用：

**Philadelphia Fed RTDSM（Real-Time Data Set for Macroeconomists）**

优先导入：

```text
Real GDP
Nominal GDP
GDI
CPI
GDP deflator
Industrial Production
Unemployment
Employment
Housing
Income
Consumption
Money
```

如果 RTDSM 没覆盖，再用 BLS、BEA、Federal Reserve 的公开网页、静态文件或 bulk download 补充。

---

## 4. 全球 P2

主要使用：

### OECD Short-term Economic Statistics Revisions

优先国家：

```text
Japan
Germany
France
UK
Italy
Spain
Canada
Australia
Korea
India
Brazil
Mexico
```

如果 OECD 有中国，也只作为中国官方数据的交叉验证源。

### DBnomics

只用于：

```text
补充覆盖
metadata discovery
cross validation
长尾国家
```

不能默认认为 DBnomics 历史值就是 PIT 历史值，除非对应 dataset 本身包含 vintage/revision 维度。

---

## 5. PIT 等级设计

每条 observation 必须包含：

```text
pit_grade
```

### PIT_A
历史原始数据 + 实际发布时间均存在。

### PIT_B
历史原始值存在，而且知道发布日期，但没有准确发布时间。

保守处理：

```text
available_at = next_day 00:00 local time
```

### PIT_C
只有发布日期和目前数据库中的历史值，original vintage 不能被证明。

不得进入 strict_pit。

### PIT_D
只有今天能抓到的终值。

历史不可用于 PIT，只允许从 `first_seen_at` 开始成为合法数据。

---

## 6. 数据库模型

底层必须使用 long format。

### observation_vintage

```text
country
source
canonical_series_id
source_series_id
series_name
frequency
unit
seasonal_adjustment
period
period_start
period_end
value
release_at
release_date_source
first_seen_at
available_at
vintage_no
revision_type
pit_grade
source_url
raw_file
raw_sha256
retrieved_at
parser_version
```

---

## 7. 永远 append-only

绝对禁止：

```sql
UPDATE observation
SET value = new_value
```

任何 revision 必须新增一条 vintage，旧值永久保留。

---

## 8. Raw layer

任何网页解析之前先保存原始响应。

目录：

```text
data/
├── raw/
│   ├── cn_nbs/
│   ├── cn_pboc/
│   ├── cn_customs/
│   ├── cn_mof/
│   ├── cn_safe/
│   ├── us_philadelphia_fed/
│   ├── oecd/
│   └── dbnomics/
├── bronze/
├── silver/
├── snapshots/
└── audit/
```

文件路径：

```text
raw/{source}/{YYYY}/{MM}/{DD}/{sha256}.html
raw/{source}/{YYYY}/{MM}/{DD}/{sha256}.json
raw/{source}/{YYYY}/{MM}/{DD}/{sha256}.xlsx
```

同时记录：

```text
url
HTTP status
request time
content type
sha256
parser
```

---

## 9. source registry

建立：

```text
config/series_registry.yml
```

例如：

```yaml
CN_CPI_YOY:
  country: CN
  source: NBS
  frequency: M
  unit: pct_yoy
  pit_required: true

CN_M2_YOY:
  country: CN
  source: PBOC
  frequency: M
  unit: pct_yoy
  pit_required: true

CN_EXPORT_USD_YOY:
  country: CN
  source: CUSTOMS
  frequency: M
  unit: pct_yoy
  pit_required: true
```

所有研究代码只使用 `canonical_series_id`，不允许直接依赖中文标题。

---

## 10. Phase 1：历史发现 Discovery

第一步必须遍历各数据源，生成：

```text
source_inventory.parquet
```

字段：

```text
source
dataset
url
earliest_period
latest_period
frequency
format
archive_available
release_timestamp_available
historical_revision_available
estimated_count
```

### Phase 1 验收

必须输出：

```text
reports/source_inventory.html
```

至少回答：
- NBS 最早可以回抓到哪年
- PBOC 最早哪年
- CUSTOMS 最早哪年
- MOF 最早哪年
- SAFE 最早哪年
- 哪些有 release time
- 哪些只有 release date
- 哪些可以还原 revision

不得在 discovery 完成前开始写统一 parser。

---

## 11. Phase 2：中国历史全量 Backfill

顺序：

```text
1 NBS
2 PBOC
3 Customs
4 MOF
5 SAFE
```

每个 source：

```text
discover
↓
download raw
↓
parse
↓
normalize
↓
map series
↓
derive release_at
↓
append vintage
```

---

## 12. 发布时间规则

优先级严格定义为：

```text
① 官方页面实际 published_at
② 官方文件 metadata
③ 官方发布日程
④ 页面发布日期
⑤ first_seen_at
```

---

## 13. 历史 revision detection

对于相同：

```text
canonical_series_id + period
```

如果出现多个 value，必须全部保留。

按照 `available_at` 排序生成：

```text
vintage_no = 0
vintage_no = 1
vintage_no = 2
...
```

同时生成：

```text
revision_delta
```

---

## 14. Phase 3：美国历史 PIT

解析 RTDSM 的 wide vintage matrix 并转换成长表：

```text
period
vintage
value
```

→

```text
series_id
period
value
available_at
vintage_no
```

---

## 15. Phase 4：全球 PIT

OECD revisions 按：

```text
country + indicator + frequency
```

分块下载，不要第一次直接下载整个全集。

第一阶段覆盖：

```text
G7
Australia
Korea
India
Brazil
Mexico
```

---

## 16. Phase 5：每日增量

建立：

```bash
python -m macro_pit update
```

建议每天 23:30 Asia/Shanghai 运行一次。

流程：

```text
check source index
↓
发现新文件/网页？
↓
下载 raw
↓
hash 是否变化？
↓
parse
↓
与已有 vintage 比较
↓
new / revised？
↓
append
```

如果没有变化，不新增 observation，但保留 crawl log。

---

## 17. first_seen_at

项目上线以后必须记录：

```text
first_seen_at
```

建议同时保留：

```text
official_available_at
observed_available_at
```

历史 backfill 在证据可靠时可以：

```text
available_at = release_at
```

---

## 18. PIT 查询接口

实现：

```python
get_snapshot(
    as_of="2021-06-30 15:00:00",
    country="CN",
    pit_mode="strict"
)
```

核心 SQL：

```sql
SELECT *
FROM observation_vintage
WHERE available_at <= $as_of
AND pit_grade IN ('A', 'B')
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY canonical_series_id, period
    ORDER BY available_at DESC, vintage_no DESC
) = 1;
```

---

## 19. 月频 snapshot

实现：

```bash
python -m macro_pit build-snapshots
```

输出：

```text
snapshots/
2020-01-31.parquet
2020-02-28.parquet
2020-03-31.parquet
...
```

snapshot 必须由 vintage database 动态生成。

---

## 20. 关键 PIT 测试

假设 7 月工业增加值在 8 月 17 日 10:00 发布：

```text
snapshot 2026-07-31
```

必须不存在这条数据。

```text
snapshot 2026-08-31
```

必须存在。

---

## 21. 同日发布时间测试

假设央行在：

```text
2025-02-14 16:30
```

发布数据。

那么：

```text
as_of = 2025-02-14 15:00
```

必须不可见；

```text
as_of = 2025-02-14 17:00
```

必须可见。

---

## 22. Revision 测试

构造 synthetic 数据：

```text
2020-01 CPI

2020-02-10:
5.4

2020-03-10:
5.3
```

要求：

```text
as_of 2020-02-29 => 5.4
as_of 2020-03-31 => 5.3
```

如果两次都返回 5.3，项目直接验收失败。

---

## 23. Idempotency 测试

连续运行：

```bash
python -m macro_pit update
python -m macro_pit update
```

第二遍不得导致 observation row count 无故增加。

要求：

```text
duplicate rows = 0
```

---

## 24. Raw reproducibility

数据库中的每条记录：

```text
source_url
raw_sha256
```

必须能够定位回 raw file。

随机抽 1000 observations：

```text
>= 99.9%
```

能找到原始文件。

---

## 25. 中国核心数据验收标准

建立：

```text
reports/cn_coverage.csv
```

至少覆盖：

| 模块 | 要求 |
|---|---:|
| GDP | ✓ |
| 工业 | ✓ |
| 消费 | ✓ |
| 投资 | ✓ |
| 地产 | ✓ |
| CPI/PPI | ✓ |
| PMI | ✓ |
| 就业 | ✓ |
| M1/M2 | ✓ |
| 信贷 | ✓ |
| 社融 | ✓ |
| 出口/进口 | ✓ |
| 财政 | ✓ |
| 外储 | ✓ |
| 跨境资金 | ✓ |

最低要求：

```text
≥ 25 个中国核心 canonical series
```

对于每个指标：

```text
自其可可靠回填的 earliest_valid_period 起
expected period coverage >= 95%
```

禁止 forward fill 和 interpolate。

---

## 26. PIT 覆盖率必须单独报告

必须报告：

```text
data coverage
PIT_A coverage
PIT_B coverage
PIT_C coverage
PIT_D coverage
```

---

## 27. 美国验收

至少：

```text
15 个核心 US macro series
```

要求完整保存 RTDSM source 中的历史 vintages。

随机抽 100 个 period 与原始 RTDSM vintage matrix 比较：

```text
value match = 100%
```

---

## 28. 全球验收

第一阶段至少覆盖：

```text
US
CN
JP
DE
FR
UK
IT
CA
AU
KR
IN
BR
MX
```

全球部分最低覆盖：

```text
GDP
CPI
industrial production
unemployment
retail
```

---

## 29. 数据质量自动审计

实现：

```bash
python -m macro_pit audit
```

生成：

```text
reports/audit.html
```

必须检查：

```text
duplicate observations
missing period
unexpected frequency
unit changes
abnormal jumps
revision count
release_at missing
source_url missing
raw file missing
timezone missing
parse failures
HTTP failures
```

---

## 30. Silent parser failure 必须禁止

网页结构变化导致：

```text
原来抓100条
现在抓0条
```

时，程序不能 exit code 0。

必须设置：

```text
expected_min_rows
```

明显低于预期时：

```text
status = FAILED
```

---

## 31. 每日任务日志

输出：

```text
logs/update_YYYYMMDD.json
```

至少包含：

```text
source
HTTP success
raw downloaded
new observations
revisions
unchanged
parse errors
coverage warnings
runtime
```

最终状态：

```text
SUCCESS
PARTIAL
FAILED
```

---

## 32. CLI

至少支持：

```bash
python -m macro_pit discover
python -m macro_pit backfill --scope cn
python -m macro_pit backfill --scope us
python -m macro_pit backfill --scope global
python -m macro_pit update
python -m macro_pit audit

python -m macro_pit snapshot     --as-of "2020-06-30 15:00:00+08:00"

python -m macro_pit snapshot     --country CN     --as-of "2020-06-30 15:00:00+08:00"

python -m macro_pit export-monthly
```

---

## 33. Repository Structure

```text
macro-pit/
│
├── config/
│   ├── sources.yml
│   └── series_registry.yml
│
├── src/macro_pit/
│   ├── cli.py
│   ├── db.py
│   ├── pit.py
│   ├── snapshot.py
│   ├── audit.py
│   └── sources/
│       ├── base.py
│       ├── cn_nbs.py
│       ├── cn_pboc.py
│       ├── cn_customs.py
│       ├── cn_mof.py
│       ├── cn_safe.py
│       ├── us_rtdsm.py
│       ├── oecd.py
│       └── dbnomics.py
│
├── tests/
│   ├── test_pit.py
│   ├── test_revision.py
│   ├── test_release_time.py
│   ├── test_idempotency.py
│   ├── test_parsers/
│   └── fixtures/
│
├── data/
├── reports/
├── logs/
└── README.md
```

---

## 34. 推荐开发阶段

严格按下面顺序推进：

```text
M0
数据库 schema
+ raw archive
+ PIT query

↓

M1
NBS + PBOC

↓

验收 PIT 是否正确

↓

M2
Customs + MOF + SAFE

↓

中国验收

↓

M3
US RTDSM

↓

M4
OECD

↓

M5
DBnomics补充

↓

M6
每日任务 + audit
```

不要一开始同时写 8 个 crawler。

---

## 35. 最终 Definition of Done

### 功能

```text
[ ] 无账户
[ ] 无API key
[ ] 无付费数据
[ ] 完整历史backfill入口
[ ] 每日增量入口
[ ] PIT as-of查询
[ ] monthly snapshot
[ ] revision保存
[ ] raw archive
```

### PIT

```text
[ ] 无数据可在 release_at 前出现
[ ] revision 不覆盖初值
[ ] date-only release 使用保守时间
[ ] as-of query 单元测试通过
[ ] 15:00/16:30 同日边界测试通过
```

### 数据

```text
[ ] 中国 ≥25 核心series
[ ] 中国有效期内 >=95% coverage
[ ] US ≥15核心series
[可选] OECD主要国家完成（不影响当前中国+美国验收）
[ ] 每条记录带 pit_grade
```

### 工程

```text
[ ] pytest全部通过
[ ] update可重复运行
[ ] duplicate=0
[ ] parser silent failure检测
[ ] 自动audit report
[ ] raw -> normalized可追溯
```

---

## 36. 最终验收测试

实现：

```bash
python -m macro_pit acceptance
```

必须输出类似：

```text
========================================
MACRO PIT ACCEPTANCE TEST
========================================

No credentials required           PASS
Raw archive reproducible          PASS
Append-only revisions             PASS
Historical PIT leakage test       PASS
Same-day release boundary         PASS
Idempotent daily update           PASS

China core series             31 / 25 PASS
China coverage                 97.4% PASS
China PIT A+B                  94.1%

US core series                 22 / 15 PASS
US RTDSM vintage match        100.0% PASS

Global countries                  13 PASS

Missing raw references           0.0% PASS
Duplicate vintage rows              0 PASS

========================================
OVERALL: PASS
========================================
```

如果：

```text
Historical PIT leakage test
```

失败，整个项目一票否决。

---

## 37. strict_pit 开关

真正跑 ETF 行业轮动时：

```python
snapshot(
    as_of=t,
    pit_mode="strict"
)
```

其中 strict 只允许：

```text
PIT_A + PIT_B
```

探索研究可以使用：

```python
pit_mode="loose"
```

允许部分 PIT_C。

---

## 38. 历史回溯起点原则

不要预先规定所有指标必须从 2000 年开始。

第一次 backfill 完成后，由程序输出：

```text
earliest_valid_period
coverage
PIT_A/B/C/D coverage
```

针对每个 canonical series 决定最终可用回测起点。

核心原则：

> 宁可少几年，也不要用伪 PIT 数据填满历史。
