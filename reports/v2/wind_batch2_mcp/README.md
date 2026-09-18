# Wind 批次2（MCP 通道）：七项待下载清单已入库

日期：2026-09-15（Asia/Shanghai）。通道：wind-finance MCP `natural_language_get_edb_data`（替代首批的手工 Excel 导出）。

## 范围与结论

`reports/v2/wind_batch1/next_download_7.csv` 七项全部完成：1,694 条观测以 **WIND / PIT_D**（`release_at` 空、`available_at=first_seen_at` 归档时刻）写入主库，771,834 → 773,528。strict/loose 快照零影响（断言通过），导出文件哈希不变。内存重放幂等（1,694 inserted / 1,694 unchanged / 0 重复键）。

## 映射（名称与单位已与 Wind 元数据逐字核对）

| Wind 代码 | 指标名称 | 换算 | 目标字段 | 覆盖 |
|---|---|---|---|---|
| M0001381 | 中国:M0:同比 | % 直取 | CN_M0_YOY | 2005-01 → 2026-08 |
| M0009941 | 金融机构各项存款余额:人民币:同比 | % 直取 | CN_RMB_DEPOSIT_BAL_YOY | 2005-01 → 2026-08 |
| M0009970 | 金融机构各项贷款余额:人民币:同比 | % 直取 | CN_RMB_LOAN_BAL_YOY | 2005-01 → 2026-08 |
| M0048261 | 金融机构:新增人民币存款:累计值 | 亿元 ÷10000 | CN_NEW_RMB_DEPOSITS_YTD | 2005-01 → 2026-08 |
| M0048255 | 金融机构:新增人民币贷款:累计值 | 亿元 ÷10000 | CN_NEW_RMB_LOANS_YTD | 2005-01 → 2026-08 |
| M5201630 | 社会融资规模:累计值 | 亿元 ÷10000 | CN_TSF_FLOW_YTD | 2005-01 → 2026-08 |
| M5525755 | 社会融资规模存量 | 万亿元直取 | CN_TSF_STOCK | 2005-12 → 2026-08（2015 前为年度/季末点） |

## 隔离项（71）

- 69 个 2005 年前数据点（`before_requested_start`，与首批同规则）；
- M0009973（新增人民币贷款:**当月值**）2 个窗口块——口径与目标累计值不符，未入库，原始 JSON 保留于 `data/manual_import/wind_mcp/` 备查。正确代码为 M0048255（搜索确认："中国:金融机构:新增人民币贷款:累计值"）。

## 通道差异记录（相对首批 Excel 通道）

- MCP 返回为干净数值：无空值填零、无隐式换汇、无公式单元格；`updateDate` 为指标级单一日期（20260914），**无逐点发布日期、无版本历史**；
- 单次大请求会被截断，需按 ≤7 年窗口分次拉取（本批 2004–2010 / 2011–202608 两段）；
- 适配脚本：`scripts/ingest_wind_mcp_batch2.py`（parser_version=`wind-edb-mcp-intake/1`），校验与入库断言同 `review_wind_batch.py`；
- 原始回执：`data/manual_import/wind_mcp/batch2_*.json`（10 个文件，16 个序列块，2,035 点，`validate_wind_mcp_batch2.py` 校验 0 错误：等长、月末、严格递增、跨文件无重复键）。

## 下游刷新（已完成）

- `estimate_availability.py` 重跑：侧车 `estimated_available_v1.csv` 5,067 条（WIND 3,652 + SAFE 1,415），七序列沿用规则表 v1（滞后 12–14 天、low 置信）；
- work 模式宽表重导：覆盖率 67.7% → **77.0%**（+1,132 格，其中本批贡献 +585 格）；严格表 8,247 非空格 0 改动。验收见 `reports/v2/pit_work_step3_work_mode/README.md`。

## 使用注意

- 本批全部为**终值**，可用时间为**校准估计值**；央行类序列规则置信度 low，分析时建议做滞后 +7/+15 天敏感性测试；
- M5525755 在 2015 年前只有年度/季末点，work 表中对应月份为空属正常现象（非缺数）；
- 社融/信贷类为修订敏感字段，若后续从 Wind 终端导出历史版本链，可按既有 append-only 机制形成新 vintage。

## 追加：导出层浮点噪声清理（2026-09-15 下午）

用户反馈 work CSV 数字格式异常。排查结论：文件无文本化存储（0 引号字段、全列可解析为数值），但 11 列存在二进制浮点噪声（如 `0.28090000000000004`，源于入库换算用 `×0.0001/×0.1` 而非除法）。修复：

1. `snapshot.py` 导出层统一 `round(v, 10)`（表现层清理，不动证据层；1e-10 远低于宏观精度）；
2. `ingest_wind_mcp_batch2.py` 换算改为除法语义（`divisor=10000`），未来批次入库即为干净 double；已入库记录不重放（避免无意义 revision），由导出层舍入覆盖；
3. strict 与 work 宽表均已重导，验收复跑：严格表非空格 0 改动、覆盖率 77.0% 不变；剩余 4 列长小数（CN_CROSS_BORDER_*、CN_FX_RESERVE_USD）为 SAFE 原始精度（万美元级），非噪声。
