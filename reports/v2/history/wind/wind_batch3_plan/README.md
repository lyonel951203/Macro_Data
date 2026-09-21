# Wind 批次3 候选清单（2026-09-15 缺口分析）

依据：`remaining_gaps.csv`（主库全等级期间覆盖）+ `wind_download_checklist.csv`（60 项总清单）。
批次1（海关5+M1/M2/社融存量同比）与批次2（央行7项）已完成；本清单为剩余可补项。
Wind 代码一律现场"仅搜索"确认，不按中文名猜（批次2 教训：M0009973 当月值≠累计值）。

## P1：宽表字段，Wind 有更早/更密历史（优先）

| canonical_series_id | 搜索名建议 | 当前DB覆盖 | 补数目标 | 注意 |
|---|---|---|---|---|
| CN_PMI_MANUFACTURING | 制造业采购经理指数PMI | 2009-06 起 | 2005-01~2009-05（53个月） | Wind 自 2005-01 |
| CN_PMI_NEW_ORDERS | 制造业PMI新订单指数 | 2009-06 起 | 同上 | |
| CN_PMI_PRODUCTION | 制造业PMI生产指数 | 2009-06 起 | 同上 | |
| CN_PMI_EMPLOYMENT | 制造业PMI从业人员指数 | 2009-06 起 | 同上 | |
| CN_PMI_RAW_MATERIAL_INVENTORY | 制造业PMI原材料库存指数 | 2009-06 起 | 同上 | |
| CN_PMI_SUPPLIER_DELIVERY | 制造业PMI供应商配送时间指数 | 2009-06 起 | 同上 | 逆指数，原样入库 |
| CN_PMI_NONMANUFACTURING | 非制造业商务活动指数 | 2018-01 起 | 2007-01~2017-12 | Wind 自 2007-01 |
| CN_CPI_YOY | 居民消费价格同比CPI | 2005-01 起但仅118期 | 中段空洞 | 不修订，终值≈原值 |
| CN_PPI_YOY | 工业生产者出厂价格同比PPI | 2005-01 起但仅123期 | 中段空洞 | |
| CN_RETAIL_SALES_YOY | 社会消费品零售总额当月同比 | 2005-01 起但仅58期 | 中段空洞 | 1-2月合并口径 |
| CN_INDUSTRIAL_VALUE_ADDED_YOY | 规模以上工业增加值当月同比 | 2005-01 起但仅75期 | 中段空洞 | 1-2月合并口径 |
| CN_FAI_YTD_YOY | 固定资产投资累计同比 | 2013-09 起 | 2005-01~2013-08 + 空洞 | 累计口径，非当月 |
| CN_REAL_ESTATE_INVESTMENT_YTD_YOY | 房地产开发投资累计同比 | 2008-11 起 | 2005-01~2008-10 + 空洞 | |
| CN_MANUFACTURING_INVESTMENT_YTD_YOY | 制造业投资累计同比 | 2013-12 起 | 2005-01~2013-11 + 空洞 | |
| CN_INFRA_INVESTMENT_YTD_YOY | 基础设施投资累计同比 | 2021-09 起 | 官方起点较早，先试搜索 | 口径起点需核（不含电力口径约2014） |
| CN_NEW_HOME_SALES_AREA_YTD_YOY | 商品房销售面积累计同比 | 2022-02 起 | 2005-01~2022-01 | |
| CN_NEW_HOME_SALES_VALUE_YTD_YOY | 商品房销售额累计同比 | 2022-02 起 | 2005-01~2022-01 | |
| CN_SERVICE_PRODUCTION_YOY | 服务业生产指数当月同比 | 2017-03 起但仅56期 | 中段空洞 | 2017 前官方未发布，不补 |
| CN_URBAN_SURVEYED_UNEMPLOYMENT | 城镇调查失业率 | 2018-01 起但仅55期 | 中段空洞 | 2018 前不补（31城口径不入） |
| CN_GDP_YOY | GDP不变价当季同比 | 2013-Q1 起 | 2005-Q1~2012-Q4（32季） | **修订敏感**：终值≠当年原值，元数据标注 |

## P2：宽表字段，财政类（早期+中段空洞）

| canonical_series_id | 搜索名建议 | 当前DB覆盖 | 补数目标 |
|---|---|---|---|
| CN_GENERAL_BUDGET_REVENUE_YTD_YOY | 一般公共预算收入累计同比 | 2008-08 起 | 2005-01~2008-07 + 空洞 |
| CN_GENERAL_BUDGET_EXPENDITURE_YTD_YOY | 一般公共预算支出累计同比 | 2008-08 起 | 同上 |
| CN_TAX_REVENUE_YTD_YOY | 税收收入累计同比 | 2009-03 起 | 2005-01~2009-02 + 空洞 |
| CN_NONTAX_REVENUE_YTD_YOY | 非税收入累计同比 | 2008-11 起 | 2005-01~2008-10 + 空洞 |
| CN_GOV_FUND_REVENUE_YTD_YOY | 政府性基金预算收入累计同比 | 2013-12 起 | 先试搜索，官方起点需核 |
| CN_GOV_FUND_EXPENDITURE_YTD_YOY | 政府性基金预算支出累计同比 | 2012-09 起 | 同上 |
| CN_LAND_SALE_REVENUE_YTD_YOY | 国有土地使用权出让收入累计同比 | 2012-06 起 | 同上 |

财政类提示：历史名称变化（"公共财政收入"→"一般公共预算收入"）；发布滞后尾部到 41 天，规则表 medium 置信。

## P3：非宽表字段（清单在列，可选入库备用，不进 work 宽表）

- CN_CORE_CPI_YOY 核心CPI同比（官方 2013-01 起）
- CN_PMI_NEW_EXPORT_ORDERS 制造业PMI新出口订单（Wind 自 2005-01）
- CN_M0_STOCK / CN_M1_STOCK / CN_M2_STOCK 货币余额（M1 需区分新旧口径）
- CN_EXPORT_CNY / CN_IMPORT_CNY / CN_TRADE_BALANCE_CNY 及同比（海关人民币口径 5 项）

## 结构性不可补（Wind 也没有更早数据，不要再拉）

- CN_PMI_COMPOSITE 综合PMI：官方 2017-01 首期
- CN_URBAN_SURVEYED_UNEMPLOYMENT 2018-01 前、CN_SERVICE_PRODUCTION_YOY 2017-03 前
- CN_TSF_STOCK / CN_TSF_STOCK_YOY 2015 前月度（已拉齐年度/季末点）
- SAFE 结售汇/涉外收付款/外储 2010 前月度（P3，官方未发布）
- CN_OECD_CPI_INDEX / CN_OECD_INDUSTRIAL_PRODUCTION：规则表 eligible=false（滞后不可用恒定规则），且覆盖已超宽表窗口

## 执行要点（同批次2流程）

1. 每代码先"仅搜索"核对名称+单位+频率，再"仅提数"分窗拉取（≤7年/窗）；
2. 拉下即存 JSON 回执 → validate 脚本校验 → 映射表过目 → --ingest；
3. 换算用除法；1-2 月合并保留原样不拆单月；
4. 入库后重跑 estimate_availability + work 导出 + 验收。
