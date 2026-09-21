# PIT_work 第1步：实际发布滞后实证分布

口径：主库中国 A/B 记录，每个（序列 × 数据期）取最早一次 release_at，换算 Asia/Shanghai 日期后计算 滞后天数 = 发布日 - 数据期末日。衡量的是"数据期首次可见"的时点，不含后续修订版本。

覆盖序列数：47；首次发布样本总数：5508

| 序列 | 来源 | 频率 | 样本期数 | 滞后中位(天) | P10 | P90 | 最小 | 最大 | 发布日中位 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| CN_BANK_FX_NET_SETTLEMENT_USD | SAFE | M | 162 | 18 | 15 | 23 | 13 | 35 | 18 |
| CN_BANK_FX_SALES_USD | SAFE | M | 162 | 18 | 15 | 23 | 13 | 35 | 18 |
| CN_BANK_FX_SETTLEMENT_USD | SAFE | M | 162 | 18 | 15 | 23 | 13 | 35 | 18 |
| CN_CPI_YOY | NBS | M | 118 | 11 | 9 | 15 | 8 | 22 | 11 |
| CN_CROSS_BORDER_NET_RECEIPTS_USD | SAFE | M | 184 | 19 | 15 | 25 | 13 | 33 | 19 |
| CN_CROSS_BORDER_PAYMENTS_USD | SAFE | M | 184 | 19 | 15 | 25 | 13 | 33 | 19 |
| CN_CROSS_BORDER_RECEIPTS_USD | SAFE | M | 184 | 19 | 15 | 25 | 13 | 33 | 19 |
| CN_FAI_YTD_YOY | NBS | M | 96 | 15 | 13 | 18 | 9 | 24 | 15 |
| CN_FX_RESERVE_USD | SAFE | M | 119 | 7 | 7 | 7 | 6 | 17 | 7 |
| CN_GDP_YOY | NBS | Q | 54 | 18 | 16 | 21 | 15 | 24 | 18 |
| CN_GENERAL_BUDGET_EXPENDITURE_YTD_YOY | MOF | M | 182 | 16 | 11 | 24 | 6 | 41 | 16 |
| CN_GENERAL_BUDGET_REVENUE_YTD_YOY | MOF | M | 189 | 16 | 11 | 24 | 6 | 41 | 16 |
| CN_GOV_FUND_EXPENDITURE_YTD_YOY | MOF | M | 132 | 18 | 13 | 24 | 10 | 41 | 17 |
| CN_GOV_FUND_REVENUE_YTD_YOY | MOF | M | 131 | 18 | 13 | 24 | 10 | 41 | 17 |
| CN_INDUSTRIAL_VALUE_ADDED_YOY | NBS | M | 75 | 15 | 9 | 18 | 9 | 24 | 15 |
| CN_INFRA_INVESTMENT_YTD_YOY | NBS | M | 52 | 16 | 15 | 18 | 14 | 24 | 16 |
| CN_LAND_SALE_REVENUE_YTD_YOY | MOF | M | 125 | 18 | 13 | 25 | 10 | 41 | 17 |
| CN_M0_YOY | PBOC | M | 19 | 12 | 11 | 15 | 11 | 18 | 12 |
| CN_M1_YOY | PBOC | M | 20 | 12 | 11 | 15 | 11 | 18 | 12 |
| CN_M2_YOY | PBOC | M | 24 | 12 | 11 | 15 | 11 | 18 | 12 |
| CN_MANUFACTURING_INVESTMENT_YTD_YOY | NBS | M | 53 | 16 | 15 | 18 | 14 | 24 | 16 |
| CN_NEW_HOME_SALES_AREA_YTD_YOY | NBS | M | 48 | 16 | 15 | 18 | 14 | 24 | 16 |
| CN_NEW_HOME_SALES_VALUE_YTD_YOY | NBS | M | 48 | 16 | 15 | 18 | 14 | 24 | 16 |
| CN_NEW_RMB_DEPOSITS_YTD | PBOC | M | 7 | 12 | 12 | 15 | 11 | 18 | 12 |
| CN_NEW_RMB_LOANS_YTD | PBOC | M | 11 | 14 | 12 | 18 | 11 | 27 | 14 |
| CN_NONTAX_REVENUE_YTD_YOY | MOF | M | 182 | 16 | 11 | 24 | 6 | 41 | 16 |
| CN_OECD_CPI_INDEX | OECD | M | 402 | 62 | 60 | 1340 | 30 | 6147 | 31 |
| CN_OECD_INDUSTRIAL_PRODUCTION | OECD | M | 309 | 91 | 61 | 123 | 59 | 2860 | 31 |
| CN_PMI_COMPOSITE | NBS | M | 63 | 0 | 0 | 0 | -4 | 4 | 31 |
| CN_PMI_EMPLOYMENT | NBS | M | 205 | 0 | 0 | 1 | -4 | 11 | 30 |
| CN_PMI_MANUFACTURING | NBS | M | 205 | 0 | 0 | 1 | -4 | 11 | 30 |
| CN_PMI_NEW_ORDERS | NBS | M | 205 | 0 | 0 | 1 | -4 | 11 | 30 |
| CN_PMI_NONMANUFACTURING | NBS | M | 104 | 0 | 0 | 0 | -4 | 4 | 31 |
| CN_PMI_PRODUCTION | NBS | M | 205 | 0 | 0 | 1 | -4 | 11 | 30 |
| CN_PMI_RAW_MATERIAL_INVENTORY | NBS | M | 205 | 0 | 0 | 1 | -4 | 11 | 30 |
| CN_PMI_SUPPLIER_DELIVERY | NBS | M | 205 | 0 | 0 | 1 | -4 | 11 | 30 |
| CN_PPI_YOY | NBS | M | 123 | 11 | 9 | 16 | 8 | 25 | 11 |
| CN_REAL_ESTATE_INVESTMENT_YTD_YOY | NBS | M | 153 | 15 | 11 | 18 | 9 | 24 | 15 |
| CN_RETAIL_SALES_YOY | NBS | M | 58 | 16 | 14 | 19 | 11 | 42 | 16 |
| CN_RMB_DEPOSIT_BAL_YOY | PBOC | M | 18 | 12 | 12 | 15 | 11 | 19 | 12 |
| CN_RMB_LOAN_BAL_YOY | PBOC | M | 16 | 13 | 12 | 15 | 11 | 18 | 13 |
| CN_SERVICE_PRODUCTION_YOY | NBS | M | 56 | 16 | 15 | 18 | 14 | 24 | 16 |
| CN_TAX_REVENUE_YTD_YOY | MOF | M | 184 | 16 | 11 | 24 | 6 | 41 | 16 |
| CN_TSF_FLOW_YTD | PBOC | M | 8 | 14 | 12 | 15 | 12 | 18 | 14 |
| CN_TSF_STOCK | PBOC | M | 3 | 14 | 12 | 15 | 12 | 15 | 14 |
| CN_TSF_STOCK_YOY | PBOC | M | 3 | 14 | 12 | 15 | 12 | 15 | 14 |
| CN_URBAN_SURVEYED_UNEMPLOYMENT | NBS | M | 55 | 16 | 15 | 18 | 14 | 76 | 16 |

说明：lag_std 大或 P90 明显偏离中位数的序列，经验规则需要分时期或显式例外，不能一刀切。

## 异常核查（2026-09-15）

- **PMI 负滞后 16 行，均为真实提前发布**：2025-01 期发布于 2025-01-27（春节调休，除夕前两天）；2022-01 期发布于 2022-01-30（春节前）。规则可表述为"当月末最后一天发布，春节月可提前 1–4 天"。
- **OECD 两序列的极端滞后是批量历史入库造成的假象**：如 1993 年各期的"首次发布"全部记为 2009-11-30（版本/辑别月），不是逐期真实发布日。OECD 序列不能用恒定滞后规则，要么只用近年逐期样本、要么保留 D 级不进估计视图。
- **央行序列样本少**（M0/M1/M2 同比 19–24 期，社融 3–8 期）：历史多靠批量表（D 级），A/B 样本集中在近期，规则置信度低于 NBS/MOF/SAFE 序列，建议标注 low_confidence。
- 明细见 `neg_lag_check.txt`。
