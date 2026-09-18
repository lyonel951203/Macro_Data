# 固定时点T宏观宽表查询接口

状态日期：2026-09-16。主库：`macro_pit_v2.duckdb`。

## 查询定义

输入：

- `T`：信息截止时点。只有日期时按Asia/Shanghai当日23:59:59.999999解释。
- `scope`：`CN`为中国，`US`为美国，`GLB`为除中国和美国以外的其他11国。
- frequency：M为自然月末，Q为自然季末；默认M。
- 默认开始时间：2005-01。

输出数值宽表：

- M：索引为2005年以来的自然月末，并包含T所在月份的月末行。
- Q：索引为2005年以来的自然季末，并包含T所在季度的季末行。
- 列为该范围当前主库中的全部字段；即使某字段在T时尚不存在，也保留空列。
- 月度值只落在自己的月份；季度值只落在季末月份。
- Q不对月度值求和或平均，只保留3、6、9、12月自身的数据。
- 不做前向填充。月表未披露月份为空；季度表当前季度未披露时对应季末行为空。

## 取值顺序与修订

每个“字段＋数据期”先过滤T时点尚不可见的记录，再构造底值：

1. PIT_A；
2. 无A时使用PIT_B；
3. 无A/B时使用已达到估计可用日的Wind。

同一层级存在多个版本时，取T时点可见的最新版本。带真实修正日期的Wind修正是版本事件：修正日前使用此前底值，修正日起覆盖更早底值；如果之后又出现更晚A/B版本，则由更晚版本接续。PIT_C、普通非Wind PIT_D和未来可用版本不进入本接口。

真实GDP边界验证：2025-01-17查询2022-Q2为PIT_A的0.4；2025-01-18起为有日期Wind修正的0.8。

## 命令行

```powershell
python -m macro_pit query-wide --as-of 2026-07-31 --scope CN --frequency M
python -m macro_pit query-wide --as-of 2026-07-31 --scope CN --frequency Q
python -m macro_pit query-wide --as-of 2026-07-31 --scope US --frequency M
python -m macro_pit query-wide --as-of 2026-07-31 --scope GLB --frequency M

# 直接从全量有效事件长表还原；不访问DuckDB
python -m macro_pit query-wide --long-parquet data\exports\cn_pit_long_from_2005-01-01.parquet --as-of 2026-07-31 --scope CN --frequency Q
```

传入`--long-parquet`时，字段集合来自该Parquet，并通过`valid_from <= T < valid_to`（`valid_to`为空视为持续有效）还原T视角。未传时仍使用DuckDB；两种输入模式的输出格式一致。

也可以使用Windows入口：

```powershell
query_pit_wide.cmd 2026-07-31 CN M
query_pit_wide.cmd 2026-07-31 CN Q
query_pit_wide.cmd 2026-07-31 US M data\queries\my_us_query
```

Python入口：

```python
import duckdb
from macro_pit.asof_wide import build_as_of_wide

conn = duckdb.connect("macro_pit_v2.duckdb", read_only=True)
result = build_as_of_wide(conn, "2026-07-31", "CN", frequency="Q")
wide = result.values
conn.close()
```

## 每次输出

- `*_values.csv`、`*_values.parquet`：用户要求的数值宽表。
- `*_periods.csv`：每个格子的原始数据期。
- `*_provenance.csv`：`PIT_A`、`PIT_B`、`WIND`或`WIND_REVISION`。
- `*_metadata.csv`：字段国家、来源、频率和单位。
- `*_selected_long.csv`：实际被选中的长表版本，含`available_at`和日期证据。
- `*_query.json`：T、范围、M/Q频率、输入模式与输入文件、索引列、优先级、行列数及无前填声明。

默认写入data/queries/；季度默认文件名前缀带_q，避免覆盖月度结果。

## 2026-07-31真实验收

| 范围 | 月末行数 | 字段数 | 2026-06非空 | 2026-07非空 |
|---|---:|---:|---:|---:|
| CN | 259 | 52 | 50 | 8 |
| US | 259 | 15 | 0 | 0 |
| GLB | 259 | 53 | 0 | 0 |

CN的2026-07仅8项PMI已在当月底可见。US和GLB的6—7月为空，是当前PIT_B版次日期在T之后的结果；查询不会使用后来才获得的版本倒填T视角。

季度模式实库验收：CN / 2026-07-31 / Q为87行×52字段，索引从2005-03-31到2026-09-30；2026-03、2026-06分别有52、50项，T所在季度的2026-09行为0项，确认没有未来值、聚合或前填。相同参数从长表Parquet查询，values、periods、provenance及3,772条选中版本与DuckDB路径逐格差异均为0；M模式的10,733条选中版本也完全一致。

## 全量长表

如需一次导出2005年以来的全部PIT有效版本，不必逐个调整T或M/Q：

~~~powershell
python -m macro_pit export-long --scope CN --start-date 2005-01-01
export_pit_long.cmd CN 2005-01-01
~~~

输出使用固定文件名，表内source_frequency区分M/Q，valid_from和valid_to构成每个值的有效区间。详见[全量长表定义与验收](LONG_EXPORT.md)。

