# 当前55个宏观字段：英文、中文、覆盖时间与更新方式

生成时间：2026-09-17T13:46:50.212510+08:00。

开始时间和结束时间均指字段的原始数据期，不是宽表观察日期。结束时间只统计生成时点已经满足PIT可见条件的记录；库内最晚数据期另列，可能包含尚未到可用日的保守版本。

中国官方网页任务在Asia/Shanghai 22:00维护NBS、PBOC、MOF、SAFE和OECD的47个字段；00:00全球任务维护ChinaBond 3个市场字段。其余5个美元外贸字段保留Wind手工导入，按当前决定不接海关自动更新。

## Reviewed PIT_D fallback coverage

The 22:00 task also polls EASTMONEY_MACRO (11 fields) and SINA_MACRO (16 fields), covering 19 unique automatic fields. These sources do not own fields: they remain PIT_D and are selected only after A, B and Wind.

## NBS / 国家统计局（21项）

每日22:00：NBS官方目录自动抓取、解析并幂等入库；历史可能含Wind D，官方A/B优先。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 库内最晚期 | 当前入库来源 |
|---|---|---|---|---:|---:|---:|---|
| `CN_CPI_YOY` | Consumer Price Index YoY | 居民消费价格指数同比 | 月度 | 2005-01 | 2026-08 | 2026-08 | EASTMONEY_MACRO,NBS,SINA_MACRO,WIND |
| `CN_FAI_YTD_YOY` | Fixed Asset Investment YTD YoY | 固定资产投资累计同比 | 月度 | 2005-02 | 2026-08 | 2026-08 | NBS,SINA_MACRO,WIND |
| `CN_GDP_YOY` | Real GDP YoY | 国内生产总值实际同比 | 季度 | 2005-Q1 | 2026-Q2 | 2026-Q2 | NBS,WIND |
| `CN_INDUSTRIAL_VALUE_ADDED_YOY` | Industrial Value Added YoY | 规模以上工业增加值同比 | 月度 | 2005-01 | 2026-08 | 2026-08 | EASTMONEY_MACRO,NBS,SINA_MACRO,WIND |
| `CN_INFRA_INVESTMENT_YTD_YOY` | Infrastructure Investment YTD YoY | 基础设施投资累计同比 | 月度 | 2014-04 | 2026-08 | 2026-08 | NBS,WIND |
| `CN_MANUFACTURING_INVESTMENT_YTD_YOY` | Manufacturing Investment YTD YoY | 制造业投资累计同比 | 月度 | 2005-02 | 2026-08 | 2026-08 | NBS,SINA_MACRO,WIND |
| `CN_NEW_HOME_SALES_AREA_YTD_YOY` | Commodity Housing Sales Area YTD YoY | 商品房销售面积累计同比 | 月度 | 2005-02 | 2026-08 | 2026-08 | NBS,WIND |
| `CN_NEW_HOME_SALES_VALUE_YTD_YOY` | Commodity Housing Sales Value YTD YoY | 商品房销售额累计同比 | 月度 | 2005-02 | 2026-08 | 2026-08 | NBS,WIND |
| `CN_PMI_COMPOSITE` | Composite PMI Output Index | 综合PMI产出指数 | 月度 | 2018-01 | 2026-08 | 2026-08 | NBS |
| `CN_PMI_EMPLOYMENT` | Manufacturing PMI Employment | 制造业PMI从业人员指数 | 月度 | 2005-01 | 2026-08 | 2026-08 | NBS,SINA_MACRO,WIND |
| `CN_PMI_MANUFACTURING` | Manufacturing PMI | 制造业采购经理指数 | 月度 | 2005-01 | 2026-08 | 2026-08 | EASTMONEY_MACRO,NBS,SINA_MACRO,WIND |
| `CN_PMI_NEW_ORDERS` | Manufacturing PMI New Orders | 制造业PMI新订单指数 | 月度 | 2005-01 | 2026-08 | 2026-08 | NBS,SINA_MACRO,WIND |
| `CN_PMI_NONMANUFACTURING` | Non-Manufacturing Business Activity Index | 非制造业商务活动指数 | 月度 | 2007-01 | 2026-08 | 2026-08 | EASTMONEY_MACRO,NBS,WIND |
| `CN_PMI_PRODUCTION` | Manufacturing PMI Production | 制造业PMI生产指数 | 月度 | 2005-01 | 2026-08 | 2026-08 | NBS,SINA_MACRO,WIND |
| `CN_PMI_RAW_MATERIAL_INVENTORY` | Manufacturing PMI Raw Material Inventory | 制造业PMI原材料库存指数 | 月度 | 2005-01 | 2026-08 | 2026-08 | NBS,SINA_MACRO,WIND |
| `CN_PMI_SUPPLIER_DELIVERY` | Manufacturing PMI Supplier Delivery Time | 制造业PMI供应商配送时间指数 | 月度 | 2005-01 | 2026-08 | 2026-08 | NBS,SINA_MACRO,WIND |
| `CN_PPI_YOY` | Producer Price Index YoY | 工业生产者出厂价格指数同比 | 月度 | 2005-01 | 2026-08 | 2026-08 | EASTMONEY_MACRO,NBS,WIND |
| `CN_REAL_ESTATE_INVESTMENT_YTD_YOY` | Real Estate Development Investment YTD YoY | 房地产开发投资累计同比 | 月度 | 2005-02 | 2026-08 | 2026-08 | NBS,SINA_MACRO,WIND |
| `CN_RETAIL_SALES_YOY` | Retail Sales YoY | 社会消费品零售总额同比 | 月度 | 2005-01 | 2026-08 | 2026-08 | EASTMONEY_MACRO,NBS,SINA_MACRO,WIND |
| `CN_SERVICE_PRODUCTION_YOY` | Service Production Index YoY | 服务业生产指数同比 | 月度 | 2017-03 | 2026-08 | 2026-08 | NBS |
| `CN_URBAN_SURVEYED_UNEMPLOYMENT` | Urban Surveyed Unemployment Rate | 全国城镇调查失业率 | 月度 | 2018-01 | 2026-08 | 2026-08 | NBS |

## PBOC / 中国人民银行（10项）

每日22:00：PBOC官方目录自动尝试；robots阻止时记录失败；历史可能含Wind D。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 库内最晚期 | 当前入库来源 |
|---|---|---|---|---:|---:|---:|---|
| `CN_M0_YOY` | M0 YoY | 流通中货币M0同比 | 月度 | 2005-01 | 2026-08 | 2026-08 | EASTMONEY_MACRO,PBOC,SINA_MACRO,WIND |
| `CN_M1_YOY` | M1 YoY | 狭义货币M1同比 | 月度 | 2005-01 | 2026-08 | 2026-08 | EASTMONEY_MACRO,PBOC,SINA_MACRO,WIND |
| `CN_M2_YOY` | M2 YoY | 广义货币M2同比 | 月度 | 2005-01 | 2026-08 | 2026-08 | EASTMONEY_MACRO,PBOC,SINA_MACRO,WIND |
| `CN_NEW_RMB_DEPOSITS_YTD` | New RMB Deposits YTD | 新增人民币存款累计值 | 月度 | 2005-01 | 2026-08 | 2026-08 | PBOC,WIND |
| `CN_NEW_RMB_LOANS_YTD` | New RMB Loans YTD | 新增人民币贷款累计值 | 月度 | 2005-01 | 2026-08 | 2026-08 | PBOC,WIND |
| `CN_RMB_DEPOSIT_BAL_YOY` | RMB Deposit Balance YoY | 人民币存款余额同比 | 月度 | 2005-01 | 2026-08 | 2026-08 | PBOC,WIND |
| `CN_RMB_LOAN_BAL_YOY` | RMB Loan Balance YoY | 人民币贷款余额同比 | 月度 | 2005-01 | 2026-08 | 2026-08 | PBOC,WIND |
| `CN_TSF_FLOW_YTD` | Total Social Financing Flow YTD | 社会融资规模增量累计值 | 月度 | 2005-01 | 2026-08 | 2026-08 | PBOC,WIND |
| `CN_TSF_STOCK` | Total Social Financing Stock | 社会融资规模存量 | 月度 | 2005-12 | 2026-08 | 2026-08 | PBOC,WIND |
| `CN_TSF_STOCK_YOY` | Total Social Financing Stock YoY | 社会融资规模存量同比 | 月度 | 2005-12 | 2026-08 | 2026-08 | PBOC,WIND |

## MOF / 财政部（7项）

每日22:00：MOF官方目录只向前更新并复查最新3篇；停止历史补齐。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 库内最晚期 | 当前入库来源 |
|---|---|---|---|---:|---:|---:|---|
| `CN_GENERAL_BUDGET_EXPENDITURE_YTD_YOY` | General Public Budget Expenditure YTD YoY | 一般公共预算支出累计同比 | 月度 | 2008-08 | 2026-07 | 2026-07 | MOF |
| `CN_GENERAL_BUDGET_REVENUE_YTD_YOY` | General Public Budget Revenue YTD YoY | 一般公共预算收入累计同比 | 月度 | 2008-08 | 2026-07 | 2026-07 | EASTMONEY_MACRO,MOF |
| `CN_GOV_FUND_EXPENDITURE_YTD_YOY` | Government Fund Budget Expenditure YTD YoY | 政府性基金预算支出累计同比 | 月度 | 2012-09 | 2026-07 | 2026-07 | MOF |
| `CN_GOV_FUND_REVENUE_YTD_YOY` | Government Fund Budget Revenue YTD YoY | 政府性基金预算收入累计同比 | 月度 | 2013-12 | 2026-07 | 2026-07 | MOF |
| `CN_LAND_SALE_REVENUE_YTD_YOY` | Land-Use Rights Sale Revenue YTD YoY | 国有土地使用权出让收入累计同比 | 月度 | 2012-06 | 2026-07 | 2026-07 | MOF |
| `CN_NONTAX_REVENUE_YTD_YOY` | Nontax Revenue YTD YoY | 非税收入累计同比 | 月度 | 2008-11 | 2026-07 | 2026-07 | MOF |
| `CN_TAX_REVENUE_YTD_YOY` | Tax Revenue YTD YoY | 税收收入累计同比 | 月度 | 2009-03 | 2026-07 | 2026-07 | MOF |

## SAFE / 国家外汇管理局（7项）

每日22:00：SAFE官方目录自动抓取、解析并幂等入库。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 库内最晚期 | 当前入库来源 |
|---|---|---|---|---:|---:|---:|---|
| `CN_BANK_FX_NET_SETTLEMENT_USD` | Bank FX Net Settlement (USD) | 银行结售汇差额（当月，美元） | 月度 | 2010-01 | 2026-08 | 2026-08 | SAFE |
| `CN_BANK_FX_SALES_USD` | Bank FX Sales (USD) | 银行售汇额（当月，美元） | 月度 | 2010-01 | 2026-08 | 2026-08 | SAFE |
| `CN_BANK_FX_SETTLEMENT_USD` | Bank FX Settlement (USD) | 银行结汇额（当月，美元） | 月度 | 2010-01 | 2026-08 | 2026-08 | SAFE |
| `CN_CROSS_BORDER_NET_RECEIPTS_USD` | Cross-Border Net Receipts (USD) | 银行代客涉外收付款差额（当月，美元） | 月度 | 2010-01 | 2026-08 | 2026-08 | SAFE |
| `CN_CROSS_BORDER_PAYMENTS_USD` | Cross-Border Payments (USD) | 银行代客对外付款（当月，美元） | 月度 | 2010-01 | 2026-08 | 2026-08 | SAFE |
| `CN_CROSS_BORDER_RECEIPTS_USD` | Cross-Border Receipts (USD) | 银行代客涉外收入（当月，美元） | 月度 | 2010-01 | 2026-08 | 2026-08 | SAFE |
| `CN_FX_RESERVE_USD` | Foreign Exchange Reserves (USD) | 外汇储备余额（美元） | 月度 | 1999-12 | 2026-08 | 2026-08 | EASTMONEY_MACRO,SAFE,SINA_MACRO |

## OECD / 经济合作与发展组织（2项）

每日22:00：OECD官方SDMX修订API完整重取；按EDITION生成PIT_B。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 库内最晚期 | 当前入库来源 |
|---|---|---|---|---:|---:|---:|---|
| `CN_OECD_CPI_INDEX` | OECD China Consumer Price Index | OECD中国居民消费价格指数 | 月度 | 1993-01 | 2026-06 | 2026-07 | OECD |
| `CN_OECD_INDUSTRIAL_PRODUCTION` | OECD China Industrial Production Index | OECD中国工业生产指数 | 月度 | 1999-01 | 2026-05 | 2026-07 | OECD |

## CHINABOND / 中国债券信息网（3项）

每日00:00：中债官方收益率曲线复查最近75天，按月末最后交易日幂等追加PIT_A。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 库内最晚期 | 当前入库来源 |
|---|---|---|---|---:|---:|---:|---|
| `CN_AAA_CP_NOTE_CREDIT_SPREAD_3Y` | China AAA CP and Note Credit Spread (3Y minus 3Y CGB) | AAA级短融中票信用利差（3年减3年国债） | 月度 | 2008-01 | 2026-08 | 2026-08 | CHINABOND |
| `CN_CGB_TERM_SPREAD_10Y_1Y` | China Government Bond Term Spread (10Y minus 1Y) | 国债期限利差（10年减1年） | 月度 | 2006-03 | 2026-08 | 2026-08 | CHINABOND |
| `CN_CGB_YTM_10Y` | China 10-Year Government Bond Yield to Maturity | 10年期国债到期收益率 | 月度 | 2006-03 | 2026-08 | 2026-08 | CHINABOND |

## WIND / Wind（5项）

不自动更新：保留Wind手工导入；按用户决定不接海关官方更新。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 库内最晚期 | 当前入库来源 |
|---|---|---|---|---:|---:|---:|---|
| `CN_EXPORT_USD` | Export Value (USD, Monthly) | 出口金额（当月，美元） | 月度 | 2005-01 | 2026-08 | 2026-08 | WIND |
| `CN_EXPORT_USD_YOY` | Export Value YoY (USD) | 出口金额同比（美元口径） | 月度 | 2005-01 | 2026-08 | 2026-08 | WIND |
| `CN_IMPORT_USD` | Import Value (USD, Monthly) | 进口金额（当月，美元） | 月度 | 2005-01 | 2026-08 | 2026-08 | WIND |
| `CN_IMPORT_USD_YOY` | Import Value YoY (USD) | 进口金额同比（美元口径） | 月度 | 2005-01 | 2026-08 | 2026-08 | WIND |
| `CN_TRADE_BALANCE_USD` | Trade Balance (USD, Monthly) | 贸易差额（当月，美元） | 月度 | 2005-01 | 2026-08 | 2026-08 | WIND |

## 数据质量核对

- 主库中国字段数：55；字段代码唯一，无空的开始或结束时间。
- 更新责任分组：NBS 21、PBOC 10、MOF 7、SAFE 7、OECD 2、ChinaBond 3、Wind手工5。
- 生成时尚未达到PIT可见日、因此库内末期与当前可见末期不同的字段：2项。
- 混合来源字段保留Wind历史底座；同一期存在官方A/B记录时，工作PIT表优先使用官方记录。

## Sources receipt

- 数据库：`macro_pit_v2.duckdb`，只读聚合55个CN字段。
- 自动更新配置：`config/daily_web_update.yml`、`config/daily_global_update.yml`。
- 中文口径参考：`scripts/export_current_pit_chinese.py`及当前字段代码。
- 本清单生成器：`scripts/export_current_field_inventory.py`。
