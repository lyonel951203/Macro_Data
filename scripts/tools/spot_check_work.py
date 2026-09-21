import io

import polars as pl

w = pl.read_csv(r"data/exports/cn_pit_work_month_end_2005_20260731_values.csv")
p = pl.read_csv(r"data/exports/cn_pit_work_month_end_2005_20260731_provenance.csv")
per = pl.read_parquet(r"data/exports/cn_pit_work_month_end_2005_20260731_periods.parquet")

out = io.open(r"reports/v2/pit_work_step1_lag/spot_check.txt", "w", encoding="utf-8")
for d in ["2005-01-31", "2005-02-28", "2005-03-31"]:
    i = w["as_of_month_end"].to_list().index(d)
    out.write(
        f"{d}: M2={w['CN_M2_YOY'][i]} prov={p['CN_M2_YOY'][i]} period={per['CN_M2_YOY'][i]}"
        f" | TSF_STOCK_YOY={w['CN_TSF_STOCK_YOY'][i]} prov={p['CN_TSF_STOCK_YOY'][i]} period={per['CN_TSF_STOCK_YOY'][i]}\n"
    )
out.close()
