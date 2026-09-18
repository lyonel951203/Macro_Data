# 中国以外72个宏观字段：英文、中文、覆盖时间与更新方式

生成时间：2026-09-18T10:53:16.555222+08:00。

主库目前包含12个非中国国家及1项全球汇总、72个字段：11个国家的53项OECD修订数据、美国15项费城联储RTDSM实时数据、美国财政部3项国债收益率，以及1项IMF全球商品价格代理。

开始时间和结束时间均指原始数据期。结束时间只统计生成时点已满足PIT可见条件的记录；库内最晚期另列，可能包含尚未到可用日的保守版本。

最晚期首次披露日期取该数据期最早一个vintage的发布日期，并按来源当地日期展示；PIT可用日期按PIT_B规则保守后移至次日00:00。后续修订不会改变这里的首次披露日期。

每日全球任务在Asia/Shanghai 00:00依次刷新OECD全球清单、美国RTDSM清单、美国财政部收益率曲线、ChinaBond市场因子和IMF商品价格工作簿；以下72项均已纳入无人值守自动更新。若22:00中国任务仍在写库，国外任务等待共享锁释放后再开始。

## GLB / Global / 全球（1项，IMF）

每日00:00自动重取IMF官方商品价格工作簿；原始记录保持PIT_D，研究查询按40天保守估算可见。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `GLB_IMF_ALL_COMMODITY_PRICE_INDEX` | Global IMF Global Price Index of All Commodities | 全球IMF全球商品价格指数 | 月度 | 1980-01 | 2026-07 | 2026-09-09 | 2026-09-10 | 2026-08 |

## AUS / Australia / 澳大利亚（5项，OECD）

每日00:00自动重取OECD官方SDMX revisions清单（oecd_core_part1/part2），按EDITION幂等追加PIT_B版本。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `AU_CPI` | Australia Consumer Price Index | 澳大利亚居民消费价格指数 | 季度 | 1955-Q1 | 2026-Q2 | 2026-08-31 | 2026-09-01 | 2026-Q2 |
| `AU_INDUSTRIAL_PRODUCTION` | Australia Industrial Production Index | 澳大利亚工业生产指数 | 季度 | 1974-Q3 | 2026-Q1 | 2026-06-30 | 2026-07-01 | 2026-Q2 |
| `AU_REAL_GDP` | Australia Real GDP | 澳大利亚实际国内生产总值 | 季度 | 1959-Q3 | 2026-Q1 | 2026-06-30 | 2026-07-01 | 2026-Q2 |
| `AU_RETAIL` | Australia Retail Trade Volume Index | 澳大利亚零售贸易量指数 | 季度 | 1960-Q1 | 2025-Q2 | 2025-09-30 | 2025-10-01 | 2025-Q2 |
| `AU_UNEMPLOYMENT` | Australia Unemployment Rate | 澳大利亚失业率 | 月度 | 1967-02 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |

## BRA / Brazil / 巴西（5项，OECD）

每日00:00自动重取OECD官方SDMX revisions清单（oecd_core_part1/part2），按EDITION幂等追加PIT_B版本。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `BR_CPI` | Brazil Consumer Price Index | 巴西居民消费价格指数 | 月度 | 1970-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `BR_INDUSTRIAL_PRODUCTION` | Brazil Industrial Production Index | 巴西工业生产指数 | 月度 | 1975-01 | 2026-05 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `BR_REAL_GDP` | Brazil Real GDP | 巴西实际国内生产总值 | 季度 | 1991-Q1 | 2026-Q1 | 2026-06-30 | 2026-07-01 | 2026-Q2 |
| `BR_RETAIL` | Brazil Retail Trade Volume Index | 巴西零售贸易量指数 | 月度 | 2000-01 | 2026-05 | 2026-08-31 | 2026-09-01 | 2026-06 |
| `BR_UNEMPLOYMENT` | Brazil Unemployment Rate | 巴西失业率 | 月度 | 1981-01 | 2012-03 | 2012-05-31 | 2012-06-01 | 2012-03 |

## CAN / Canada / 加拿大（5项，OECD）

每日00:00自动重取OECD官方SDMX revisions清单（oecd_core_part1/part2），按EDITION幂等追加PIT_B版本。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `CA_CPI` | Canada Consumer Price Index | 加拿大居民消费价格指数 | 月度 | 1949-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `CA_INDUSTRIAL_PRODUCTION` | Canada Industrial Production Index | 加拿大工业生产指数 | 月度 | 1961-01 | 2026-04 | 2026-08-31 | 2026-09-01 | 2026-06 |
| `CA_REAL_GDP` | Canada Real GDP | 加拿大实际国内生产总值 | 季度 | 1961-Q1 | 2026-Q2 | 2026-08-31 | 2026-09-01 | 2026-Q2 |
| `CA_RETAIL` | Canada Retail Trade Volume Index | 加拿大零售贸易量指数 | 月度 | 1961-01 | 2026-04 | 2026-07-31 | 2026-08-01 | 2026-06 |
| `CA_UNEMPLOYMENT` | Canada Unemployment Rate | 加拿大失业率 | 月度 | 1956-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-08 |

## DEU / Germany / 德国（5项，OECD）

每日00:00自动重取OECD官方SDMX revisions清单（oecd_core_part1/part2），按EDITION幂等追加PIT_B版本。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `DE_CPI` | Germany Consumer Price Index | 德国居民消费价格指数 | 月度 | 1955-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `DE_INDUSTRIAL_PRODUCTION` | Germany Industrial Production Index | 德国工业生产指数 | 月度 | 1958-01 | 2026-05 | 2026-08-31 | 2026-09-01 | 2026-06 |
| `DE_REAL_GDP` | Germany Real GDP | 德国实际国内生产总值 | 季度 | 1991-Q1 | 2026-Q2 | 2026-08-31 | 2026-09-01 | 2026-Q2 |
| `DE_RETAIL` | Germany Retail Trade Volume Index | 德国零售贸易量指数 | 月度 | 1955-01 | 2026-05 | 2026-07-31 | 2026-08-01 | 2026-06 |
| `DE_UNEMPLOYMENT` | Germany Unemployment Rate | 德国失业率 | 月度 | 1978-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |

## FRA / France / 法国（5项，OECD）

每日00:00自动重取OECD官方SDMX revisions清单（oecd_core_part1/part2），按EDITION幂等追加PIT_B版本。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `FR_CPI` | France Consumer Price Index | 法国居民消费价格指数 | 月度 | 1955-01 | 2025-12 | 2026-02-28 | 2026-03-01 | 2025-12 |
| `FR_INDUSTRIAL_PRODUCTION` | France Industrial Production Index | 法国工业生产指数 | 月度 | 1956-01 | 2026-04 | 2026-06-30 | 2026-07-01 | 2026-06 |
| `FR_REAL_GDP` | France Real GDP | 法国实际国内生产总值 | 季度 | 1949-Q1 | 2026-Q2 | 2026-08-31 | 2026-09-01 | 2026-Q2 |
| `FR_RETAIL` | France Retail Trade Volume Index | 法国零售贸易量指数 | 月度 | 1975-01 | 2026-05 | 2026-07-31 | 2026-08-01 | 2026-07 |
| `FR_UNEMPLOYMENT` | France Unemployment Rate | 法国失业率 | 月度 | 1978-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |

## GBR / United Kingdom / 英国（5项，OECD）

每日00:00自动重取OECD官方SDMX revisions清单（oecd_core_part1/part2），按EDITION幂等追加PIT_B版本。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `UK_CPI` | United Kingdom Consumer Price Index | 英国居民消费价格指数 | 月度 | 1955-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `UK_INDUSTRIAL_PRODUCTION` | United Kingdom Industrial Production Index | 英国工业生产指数 | 月度 | 1956-01 | 2026-05 | 2026-08-31 | 2026-09-01 | 2026-06 |
| `UK_REAL_GDP` | United Kingdom Real GDP | 英国实际国内生产总值 | 季度 | 1955-Q1 | 2026-Q1 | 2026-06-30 | 2026-07-01 | 2026-Q2 |
| `UK_RETAIL` | United Kingdom Retail Trade Volume Index | 英国零售贸易量指数 | 月度 | 1957-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `UK_UNEMPLOYMENT` | United Kingdom Unemployment Rate | 英国失业率 | 月度 | 1971-01 | 2026-04 | 2026-08-31 | 2026-09-01 | 2026-05 |

## IND / India / 印度（3项，OECD）

每日00:00自动重取OECD官方SDMX revisions清单（oecd_core_part1/part2），按EDITION幂等追加PIT_B版本。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `IN_CPI` | India Consumer Price Index | 印度居民消费价格指数 | 月度 | 1957-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `IN_INDUSTRIAL_PRODUCTION` | India Industrial Production Index | 印度工业生产指数 | 月度 | 1994-04 | 2011-03 | 2011-06-30 | 2011-07-01 | 2011-03 |
| `IN_REAL_GDP` | India Real GDP | 印度实际国内生产总值 | 季度 | 1996-Q2 | 2014-Q3 | 2014-12-31 | 2015-01-01 | 2014-Q3 |

## ITA / Italy / 意大利（5项，OECD）

每日00:00自动重取OECD官方SDMX revisions清单（oecd_core_part1/part2），按EDITION幂等追加PIT_B版本。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `IT_CPI` | Italy Consumer Price Index | 意大利居民消费价格指数 | 月度 | 1955-01 | 2025-12 | 2026-02-28 | 2026-03-01 | 2025-12 |
| `IT_INDUSTRIAL_PRODUCTION` | Italy Industrial Production Index | 意大利工业生产指数 | 月度 | 1955-01 | 2026-05 | 2026-08-31 | 2026-09-01 | 2026-06 |
| `IT_REAL_GDP` | Italy Real GDP | 意大利实际国内生产总值 | 季度 | 1970-Q1 | 2026-Q2 | 2026-08-31 | 2026-09-01 | 2026-Q2 |
| `IT_RETAIL` | Italy Retail Trade Volume Index | 意大利零售贸易量指数 | 月度 | 1970-01 | 2026-05 | 2026-07-31 | 2026-08-01 | 2026-07 |
| `IT_UNEMPLOYMENT` | Italy Unemployment Rate | 意大利失业率 | 月度 | 1978-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |

## JPN / Japan / 日本（5项，OECD）

每日00:00自动重取OECD官方SDMX revisions清单（oecd_core_part1/part2），按EDITION幂等追加PIT_B版本。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `JP_CPI` | Japan Consumer Price Index | 日本居民消费价格指数 | 月度 | 1955-01 | 2022-04 | 2022-06-30 | 2022-07-01 | 2022-04 |
| `JP_INDUSTRIAL_PRODUCTION` | Japan Industrial Production Index | 日本工业生产指数 | 月度 | 1955-01 | 2026-05 | 2026-08-31 | 2026-09-01 | 2026-06 |
| `JP_REAL_GDP` | Japan Real GDP | 日本实际国内生产总值 | 季度 | 1960-Q1 | 2026-Q1 | 2026-06-30 | 2026-07-01 | 2026-Q2 |
| `JP_RETAIL` | Japan Retail Trade Volume Index | 日本零售贸易量指数 | 月度 | 1960-01 | 2026-05 | 2026-08-31 | 2026-09-01 | 2026-06 |
| `JP_UNEMPLOYMENT` | Japan Unemployment Rate | 日本失业率 | 月度 | 1955-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |

## KOR / South Korea / 韩国（5项，OECD）

每日00:00自动重取OECD官方SDMX revisions清单（oecd_core_part1/part2），按EDITION幂等追加PIT_B版本。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `KR_CPI` | South Korea Consumer Price Index | 韩国居民消费价格指数 | 月度 | 1951-08 | 2026-06 | 2026-07-31 | 2026-08-01 | 2026-07 |
| `KR_INDUSTRIAL_PRODUCTION` | South Korea Industrial Production Index | 韩国工业生产指数 | 月度 | 1989-01 | 2026-05 | 2026-07-31 | 2026-08-01 | 2026-07 |
| `KR_REAL_GDP` | South Korea Real GDP | 韩国实际国内生产总值 | 季度 | 1960-Q1 | 2026-Q2 | 2026-08-31 | 2026-09-01 | 2026-Q2 |
| `KR_RETAIL` | South Korea Retail Trade Volume Index | 韩国零售贸易量指数 | 月度 | 1990-01 | 2026-05 | 2026-07-31 | 2026-08-01 | 2026-07 |
| `KR_UNEMPLOYMENT` | South Korea Unemployment Rate | 韩国失业率 | 月度 | 1989-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |

## MEX / Mexico / 墨西哥（5项，OECD）

每日00:00自动重取OECD官方SDMX revisions清单（oecd_core_part1/part2），按EDITION幂等追加PIT_B版本。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `MX_CPI` | Mexico Consumer Price Index | 墨西哥居民消费价格指数 | 月度 | 1960-01 | 2026-01 | 2026-03-31 | 2026-04-01 | 2026-01 |
| `MX_INDUSTRIAL_PRODUCTION` | Mexico Industrial Production Index | 墨西哥工业生产指数 | 月度 | 1975-01 | 2026-05 | 2026-08-31 | 2026-09-01 | 2026-06 |
| `MX_REAL_GDP` | Mexico Real GDP | 墨西哥实际国内生产总值 | 季度 | 1980-Q1 | 2026-Q2 | 2026-08-31 | 2026-09-01 | 2026-Q2 |
| `MX_RETAIL` | Mexico Retail Trade Volume Index | 墨西哥零售贸易量指数 | 月度 | 1986-01 | 2026-05 | 2026-08-31 | 2026-09-01 | 2026-06 |
| `MX_UNEMPLOYMENT` | Mexico Unemployment Rate | 墨西哥失业率 | 月度 | 1985-01 | 2026-06 | 2026-08-31 | 2026-09-01 | 2026-07 |

## US / United States / 美国（18项，RTDSM, USTREASURY）

每日00:00自动重取费城联储RTDSM官方vintage工作簿（rtdsm_core.yml），幂等追加PIT_B版本。<br>每日00:00自动读取美国财政部官方Daily Treasury Par Yield Curve Rates XML；取每月最后交易日，发布日期次日00:00（America/New_York）可见，记为PIT_B。

| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |
|---|---|---|---|---:|---:|---:|---:|---:|
| `US_CONSUMPTION` | United States Nominal Personal Consumption Expenditures | 美国名义个人消费支出 | 季度 | 1947-Q1 | 2026-Q2 | 2026-08-15 | 2026-08-16 | 2026-Q2 |
| `US_CORE_CPI` | United States Core Consumer Price Index | 美国核心居民消费价格指数 | 月度 | 1957-01 | 2026-07 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `US_CPI` | United States Consumer Price Index | 美国居民消费价格指数 | 月度 | 1947-01 | 2026-07 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `US_EMPLOYMENT` | United States Nonfarm Payroll Employment | 美国非农就业人数 | 月度 | 1939-01 | 2026-07 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `US_GDI` | United States Real Gross Domestic Income | 美国实际国内总收入 | 季度 | 1947-Q1 | 2026-Q1 | 2026-06-30 | 2026-07-01 | 2026-Q2 |
| `US_GDP_DEFLATOR` | United States GDP Price Index | 美国GDP价格指数 | 季度 | 1947-Q1 | 2026-Q2 | 2026-08-31 | 2026-09-01 | 2026-Q2 |
| `US_HOUSING_STARTS` | United States Housing Starts | 美国新屋开工 | 月度 | 1947-01 | 2026-07 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `US_INDUSTRIAL_PRODUCTION` | United States Industrial Production Index | 美国工业生产指数 | 月度 | 1919-01 | 2026-07 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `US_LABOR_FORCE` | United States Civilian Labor Force | 美国劳动力人口 | 月度 | 1948-01 | 2026-07 | 2026-08-31 | 2026-09-01 | 2026-07 |
| `US_MONEY_M1` | United States M1 Money Stock | 美国M1货币存量 | 月度 | 1947-01 | 2026-06 | 2026-08-15 | 2026-08-16 | 2026-06 |
| `US_MONEY_M2` | United States M2 Money Stock | 美国M2货币存量 | 月度 | 1959-01 | 2026-06 | 2026-08-15 | 2026-08-16 | 2026-06 |
| `US_NOMINAL_GDP` | United States Nominal GDP | 美国名义国内生产总值 | 季度 | 1947-Q1 | 2026-Q2 | 2026-08-31 | 2026-09-01 | 2026-Q2 |
| `US_REAL_CONSUMPTION` | United States Real Personal Consumption Expenditures | 美国实际个人消费支出 | 季度 | 1947-Q1 | 2026-Q2 | 2026-08-31 | 2026-09-01 | 2026-Q2 |
| `US_REAL_GDP` | United States Real GDP | 美国实际国内生产总值 | 季度 | 1947-Q1 | 2026-Q2 | 2026-08-31 | 2026-09-01 | 2026-Q2 |
| `US_TREASURY_YIELD_10Y` | United States 10-Year Treasury Constant Maturity Rate | 美国10年期国债恒定到期收益率 | 月度 | 2005-01 | 2026-08 | 2026-09-01 | 2026-09-01 | 2026-08 |
| `US_TREASURY_YIELD_2Y` | United States 2-Year Treasury Constant Maturity Rate | 美国2年期国债恒定到期收益率 | 月度 | 2005-01 | 2026-08 | 2026-09-01 | 2026-09-01 | 2026-08 |
| `US_TREASURY_YIELD_30Y` | United States 30-Year Treasury Constant Maturity Rate | 美国30年期国债恒定到期收益率 | 月度 | 2006-02 | 2026-08 | 2026-09-01 | 2026-09-01 | 2026-08 |
| `US_UNEMPLOYMENT` | United States Unemployment Rate | 美国失业率 | 月度 | 1948-01 | 2026-07 | 2026-08-15 | 2026-08-16 | 2026-07 |

## 数据质量核对

- 非中国字段数：72；字段代码唯一，中英文名称及起止期均完整。
- 72项均补充最晚PIT可见数据期的首次披露日期、PIT可用日期和日期证据来源。
- 来源分布：OECD 53项、RTDSM 15项、美国财政部3项、IMF 1项。
- 国家分布：澳大利亚、巴西、加拿大、德国、法国、英国、印度、意大利、日本、韩国、墨西哥、美国，共12国；另含全球汇总1项。
- 生成时库内末期与当前PIT可见末期不同：40项。
- 当前可见结束年份早于2025年的陈旧/终止序列：4项；具体字段见quality_summary.json。

## Sources receipt

- 数据库：`macro_pit_v2.duckdb`，只读聚合所有country不等于CN的记录。
- OECD清单：`config/oecd_core_part1.yml`、`config/oecd_core_part2.yml`。
- 美国RTDSM清单：`config/rtdsm_core.yml`。
- 美国财政部日度曲线：`src/macro_pit/sources/us_treasury.py`。
- 每日任务配置：`config/daily_global_update.yml`，OECD、RTDSM、美国财政部、ChinaBond和IMF均已调度。
- 本清单生成器：`scripts/export_non_cn_field_inventory.py`。
