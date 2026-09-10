# PIT 字段历史覆盖检查

范围：当前 2005-01 至 2026-07 月末 CSV 的全部 47 个指标；主库以只读方式核对。

首次有值是本 CSV 的月末日期，首条数据期是该单元格对应的统计月份/季度；两者都不代表官方指标创设日期。
已入库期数仅统计截至 2026-07-31 23:59:59（上海时间）可用的 A/B 记录，按原始数据期去重。
该期数包含起始月末以前的历史数据，也可能包含从未被月末最新值选中的数据期；不等于非空快照月数。

| 字段 | 名称 | 来源 | CSV 首次有值 | 首条数据期 | 截止日 A/B 已入库期数 |
| --- | --- | --- | --- | --- | ---: |
| CN_GENERAL_BUDGET_EXPENDITURE_YTD_YOY | 一般公共预算支出累计同比 | MOF | 2008-09-30 | 2008-08 | 181 |
| CN_GENERAL_BUDGET_REVENUE_YTD_YOY | 一般公共预算收入累计同比 | MOF | 2008-09-30 | 2008-08 | 188 |
| CN_NONTAX_REVENUE_YTD_YOY | 非税收入累计同比 | MOF | 2008-12-31 | 2008-11 | 181 |
| CN_TAX_REVENUE_YTD_YOY | 税收收入累计同比 | MOF | 2009-04-30 | 2009-03 | 183 |
| CN_LAND_SALE_REVENUE_YTD_YOY | 国有土地出让收入累计同比 | MOF | 2012-07-31 | 2012-06 | 124 |
| CN_GOV_FUND_EXPENDITURE_YTD_YOY | 政府性基金预算支出累计同比 | MOF | 2012-10-31 | 2012-09 | 131 |
| CN_GOV_FUND_REVENUE_YTD_YOY | 政府性基金预算收入累计同比 | MOF | 2014-01-31 | 2013-12 | 130 |
| CN_CPI_YOY | 居民消费价格同比 | NBS | 2005-02-28 | 2005-01 | 81 |
| CN_INDUSTRIAL_VALUE_ADDED_YOY | 规模以上工业增加值同比 | NBS | 2005-02-28 | 2005-01 | 54 |
| CN_PPI_YOY | 工业生产者出厂价格同比 | NBS | 2005-02-28 | 2005-01 | 85 |
| CN_RETAIL_SALES_YOY | 社会消费品零售总额同比 | NBS | 2005-03-31 | 2005-02 | 55 |
| CN_FAI_YTD_YOY | 固定资产投资累计同比 | NBS | 2015-04-30 | 2015-03 | 60 |
| CN_SERVICE_PRODUCTION_YOY | 服务业生产指数同比 | NBS | 2017-04-30 | 2017-03 | 53 |
| CN_PMI_COMPOSITE | 综合PMI产出指数 | NBS | 2018-01-31 | 2018-01 | 62 |
| CN_PMI_EMPLOYMENT | 制造业PMI从业人员指数 | NBS | 2018-01-31 | 2018-01 | 103 |
| CN_PMI_MANUFACTURING | 制造业采购经理指数 | NBS | 2018-01-31 | 2018-01 | 103 |
| CN_PMI_NEW_ORDERS | 制造业PMI新订单指数 | NBS | 2018-01-31 | 2018-01 | 103 |
| CN_PMI_NONMANUFACTURING | 非制造业商务活动指数 | NBS | 2018-01-31 | 2018-01 | 103 |
| CN_PMI_PRODUCTION | 制造业PMI生产指数 | NBS | 2018-01-31 | 2018-01 | 103 |
| CN_PMI_RAW_MATERIAL_INVENTORY | 制造业PMI原材料库存指数 | NBS | 2018-01-31 | 2018-01 | 103 |
| CN_PMI_SUPPLIER_DELIVERY | 制造业PMI供应商配送时间指数 | NBS | 2018-01-31 | 2018-01 | 103 |
| CN_URBAN_SURVEYED_UNEMPLOYMENT | 城镇调查失业率 | NBS | 2018-04-30 | 2018-03 | 54 |
| CN_GDP_YOY | 国内生产总值同比 | NBS | 2021-10-31 | 2021-Q3 | 20 |
| CN_INFRA_INVESTMENT_YTD_YOY | 基础设施投资累计同比 | NBS | 2021-10-31 | 2021-09 | 51 |
| CN_MANUFACTURING_INVESTMENT_YTD_YOY | 制造业投资累计同比 | NBS | 2021-10-31 | 2021-09 | 51 |
| CN_REAL_ESTATE_INVESTMENT_YTD_YOY | 房地产开发投资累计同比 | NBS | 2021-10-31 | 2021-09 | 51 |
| CN_NEW_HOME_SALES_AREA_YTD_YOY | 新建商品房销售面积累计同比 | NBS | 2022-03-31 | 2022-02 | 47 |
| CN_NEW_HOME_SALES_VALUE_YTD_YOY | 新建商品房销售额累计同比 | NBS | 2022-03-31 | 2022-02 | 47 |
| CN_OECD_CPI_INDEX | OECD China consumer prices | OECD | 2005-01-31 | 2004-10 | 400 |
| CN_OECD_INDUSTRIAL_PRODUCTION | OECD China industrial production | OECD | 2005-01-31 | 2004-08 | 308 |
| CN_M0_YOY | M0同比 | PBOC | 2010-01-31 | 2009-12 | 4 |
| CN_M1_YOY | M1同比 | PBOC | 2010-01-31 | 2009-12 | 4 |
| CN_M2_YOY | M2同比 | PBOC | 2010-01-31 | 2009-12 | 4 |
| CN_NEW_RMB_DEPOSITS_YTD | 新增人民币存款累计 | PBOC | 2010-01-31 | 2009-12 | 4 |
| CN_NEW_RMB_LOANS_YTD | 新增人民币贷款累计 | PBOC | 2010-01-31 | 2009-12 | 4 |
| CN_RMB_DEPOSIT_BAL_YOY | 人民币存款余额同比 | PBOC | 2010-01-31 | 2009-12 | 4 |
| CN_RMB_LOAN_BAL_YOY | 人民币贷款余额同比 | PBOC | 2010-01-31 | 2009-12 | 4 |
| CN_TSF_FLOW_YTD | 社会融资规模增量累计 | PBOC | 2026-06-30 | 2026-05 | 2 |
| CN_TSF_STOCK | 社会融资规模存量 | PBOC | 2026-06-30 | 2026-05 | 2 |
| CN_TSF_STOCK_YOY | 社会融资规模存量同比 | PBOC | 2026-06-30 | 2026-05 | 2 |
| CN_BANK_FX_NET_SETTLEMENT_USD | 银行结售汇差额 | SAFE | 2024-08-31 | 2024-07 | 24 |
| CN_BANK_FX_SALES_USD | 银行售汇 | SAFE | 2024-08-31 | 2024-07 | 24 |
| CN_BANK_FX_SETTLEMENT_USD | 银行结汇 | SAFE | 2024-08-31 | 2024-07 | 24 |
| CN_CROSS_BORDER_NET_RECEIPTS_USD | 涉外收付款差额 | SAFE | 2024-08-31 | 2024-07 | 24 |
| CN_CROSS_BORDER_PAYMENTS_USD | 对外付款 | SAFE | 2024-08-31 | 2024-07 | 24 |
| CN_CROSS_BORDER_RECEIPTS_USD | 涉外收入 | SAFE | 2024-08-31 | 2024-07 | 24 |
| CN_FX_RESERVE_USD | 外汇储备 | SAFE | 2024-09-30 | 2024-08 | 23 |

主要发现：

- 16/47 个字段首次有值在 2021 年以后；全表指标单元格空值占 51.03%。
- CPI/PPI 虽从 2005 年出现，但在 2005-01 至 2026-06 的 258 个原始月份中仅有 81/85 个月，分别缺 177/173 个月。
- 实体经济严格 A/B 数据仍稀疏：规模以上工业增加值同比 54 个月（2005-01 起）；社会消费品零售总额同比 55 个月（2005-01 起）；固定资产投资累计同比 60 个月（2015-03 起）；服务业生产指数同比 53 个月（2017-03 起）；城镇调查失业率 54 个月（2018-01 起）；基础设施投资累计同比 51 个月（2021-09 起）；制造业投资累计同比 51 个月（2021-09 起）；房地产开发投资累计同比 51 个月（2021-09 起）。最早日期提前不等于中间月份已经补齐。
- PBOC 严格 A/B 覆盖：M0同比 4 个月；M1同比 4 个月；M2同比 4 个月；新增人民币存款累计 4 个月；新增人民币贷款累计 4 个月；人民币存款余额同比 4 个月；人民币贷款余额同比 4 个月；社会融资规模增量累计 2 个月；社会融资规模存量 2 个月；社会融资规模存量同比 2 个月。此处仅统计截止日前可用的官方记录。
- SAFE 早期历史存在于主库：外储始于 1999-12，其余六项始于 2010-01；早期 C/D 记录无法进入严格 A/B 快照，仍缺原始发布证据。
- PMI 的真实月份和月末选中月份分别见 strict_periods_by_cutoff 与 distinct_selected_source_periods 两列；月末仅取当时最新期，二者差额不能直接判作漏抓。GDP 在 2021-Q3 至 2026-Q2 间已入库 20 个季度。
- OECD 首次出现在 2005-01 是导出窗口限制；首条快照分别采用 2004-10 CPI 和 2004-08 工业生产指数，主库更早历史已存在。
- 财政部分月份缺失需结合发布口径判断，不能将累计指标的每个自然月都机械认定为必发月份。
- 现有覆盖目录有 13 个字段在所有等级中均未入库；另有 18 个字段在截止日前没有严格 A/B 记录，不在当前 47 列中。两种缺口分别列出，不能混用。

后续优先处理 NBS 已有候选正文入库及综合稿漏解析，再补 PBOC 历史和 SAFE 原始发布时间证据；回测需同时检查数据期和陈旧程度。

完整 CSV：field_history.csv；价格缺口：price_missing_ranges.csv；空缺目录：unpopulated_catalogue_fields.csv。
复核代码：field_history_review.ipynb / field_history_review.py。该复核脚本不修改原始 CSV 或主库，也不运行全库验收。
