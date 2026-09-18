# 全量PIT有效事件长表

状态日期：2026-09-16。主库：macro_pit_v2.duckdb。

这个导出用于一次保存2005年以来的完整PIT历史，不需要反复修改T、M/Q并保存带时间戳的宽表。

## 使用

~~~powershell
python -m macro_pit export-long --scope CN --start-date 2005-01-01
export_pit_long.cmd CN 2005-01-01
~~~

scope支持CN、US、GLB和ALL。end-date可选；不传时输出库内全部数据期。默认输出前缀固定为：

~~~text
data/exports/cn_pit_long_from_2005-01-01
~~~

重复执行会刷新同名CSV、Parquet和JSON回执，不产生新的时间戳文件。若要保留一个冻结版本，可以显式传入output-prefix。

## 行定义

一行表示一个“国家＋字段＋数据期”的有效值事件：

| 列 | 含义 |
|---|---|
| country | 国家 |
| canonical_series_id | 标准字段 |
| source_frequency | 原始频率M或Q |
| period、period_start、period_end | 数据所属期 |
| value | 该版本数值 |
| valid_from | 该值开始可见，包含此时点 |
| valid_to | 该值失效时点，不包含此时点；空值表示持续有效 |
| selection_origin | PIT_A、PIT_B、WIND或WIND_REVISION |
| event_role | 普通优先级底值或有日期修订事件 |
| source_priority | A=3、B=2、Wind=1 |
| source、raw_file、raw_sha256等 | 来源与原稿审计信息 |

表内已经按A、B、Wind优先级剔除永远不会生效的低优先级版本。带真实日期的Wind修订保留为独立事件；修订后若出现更晚A/B版本，也会形成新的有效事件。PIT_C和普通非Wind PIT_D不进入此表。

## 查询任意T

长表Parquet可以直接复用`query-wide`，无需访问DuckDB或Wind发布日期侧车：

~~~powershell
python -m macro_pit query-wide `
  --long-parquet data\exports\cn_pit_long_from_2005-01-01.parquet `
  --as-of 2026-07-31 --scope CN --frequency Q
~~~

内部按以下有效区间筛选，再按`period_end`透视：

~~~text
valid_from <= T
并且
valid_to为空 或 T < valid_to
~~~

`M`和`Q`控制输出索引。`Q`保留自然季末行，也保留3、6、9、12月自身的月度指标；它不是只筛选`source_frequency=Q`，不会聚合或前向填充。省略`--long-parquet`时，`query-wide`仍从DuckDB和发布日期侧车即时构造相同结果。

## 真实验收

CN从2005-01-01开始导出12,073行、52字段：

- PIT_A：3,685行
- PIT_B：2,572行
- Wind普通值：5,808行
- Wind有日期修订：8行
- 月频：11,978行
- 季频：95行

有效区间倒置为0。按2026-07-31查询时，长表与DuckDB路径逐格比较：M为259行×52字段、选中10,733条，Q为87行×52字段、选中3,772条；数值、数据期、来源标签和选中版本差异均为0。