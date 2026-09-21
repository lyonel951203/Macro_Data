# Wind MCP 中段缺期补充（2026-09-21）

本轮使用 Wind `economic_data.query_economic_indicator_data` 精确代码拉取，只追加来源 `WIND`、等级 `D` 的记录；官方 A/B 记录不覆盖。主库新增128条，严格 A/B 快照和既有严格导出保持不变。

| 字段 | Wind代码 | 审核与新增 | 当前连续覆盖 |
|---|---|---|---:|
| `CN_PMI_COMPOSITE` | `M5809944` | 2018—2021窗口48期；官方重叠7/7一致；新增41期 | 2018-01—2026-08，104/104 |
| `CN_URBAN_SURVEYED_UNEMPLOYMENT` | `M5650805` | 全窗口104期；官方重叠56期中54期完全一致，2期仅有0.04个百分点精度差；新增48期 | 2018-01—2026-08，104/104 |
| `CN_SERVICE_PRODUCTION_YOY` | `M5767203` | 全窗口99期；最新官方重叠57/57一致；新增39个非1—2月缺期 | 2017-03—2026-08，96/114 |

## PIT 处理

普通 Wind 记录的 `release_at` 为空，主库 `available_at` 是本次实际首次取得时间。研究侧车 `estimated_available_v1.csv` 才保存经验或官方锚定的可得时点，固定T查询和复合长表从侧车生成有效区间。

调查失业率有10期逐期官方锚定：2019—2021年1月，以及2022-01、2022-04、2023-01、2024-01、2025-01、2025-12、2026-01；详见 [2019—2021核查](../surveyed_unemployment_jan_2019_2021_pit_evidence.md) 和 [2022—2026核查](../surveyed_unemployment_gaps_2022_2026_pit_evidence.md)。其他 D 级记录继续使用指标规则的经验发布日期。

服务业生产指数的2017—2019年2月 Wind 值实际代表1—2月合并同比，不能写入“当月同比”单月字段；详情见 [服务业补缺报告](service_production/README.md)。因此剩余18个1—2月缺口明确保留，不以合并值冒充单月值。

## 批次与验收

| 批次 | 内容 | 入库条数 |
|---|---|---:|
| batch10 | 综合PMI 41 + 调查失业率38 | 79 |
| batch11 | 2019—2021年1月调查失业率 | 3 |
| batch12 | 2022—2026年调查失业率剩余缺期 | 7 |
| batch13 | 服务业生产指数非1—2月安全缺期 | 39 |
| 合计 |  | 128 |

batch12和batch13均为0隔离、0重复字段期，隔离库重放全部 unchanged。调查失业率7期完成14个发布边界检查；服务业完成主库/长表39条一致性和6个代表性边界检查。复合长表已刷新为239,987条版本事件。

运行顺序：

```powershell
python scripts/stage_wind_unemployment_gaps_2022_2026.py
python scripts/ingest_wind_mcp.py --pattern batch12_unemployment_gaps_2022_2026.json --output-dir reports/v2/wind_midgap_20260921/unemployment_2022_2026 --ingest
python scripts/stage_wind_service_gaps_20260921.py
python scripts/ingest_wind_mcp.py --pattern batch13_service_production_safe_gaps.json --output-dir reports/v2/wind_midgap_20260921/service_production --ingest
python scripts/estimate_availability.py
python -m macro_pit --db-path macro_pit_v2.duckdb export-long --scope ALL --start-date 2005-01-01
```

原始回执、请求窗口、SHA-256、映射、入库回执和时间边界应一起保留。Wind 指标级 `updateDate` 只能说明当前序列更新时间，不能单独重建逐点修订历史。
