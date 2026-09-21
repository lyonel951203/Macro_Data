import duckdb, json
from pathlib import Path
ROOT=Path(r"E:\Macro_Data")
DB=ROOT/"macro_pit_v2.duckdb"
LONG=ROOT/"data"/"exports"/"all_pit_long_from_2005-01-01.parquet"
ids=[
"CN_EXPORT_USD","CN_EXPORT_USD_YOY","CN_IMPORT_USD","CN_IMPORT_USD_YOY","CN_TRADE_BALANCE_USD"
]
con=duckdb.connect(str(DB),read_only=True)
ph=",".join(["?"]*len(ids))
q=f"""
with base as (
 select *, count(*) over(partition by canonical_series_id,period) as n_per_period,
        count(distinct value) over(partition by canonical_series_id,period) as n_values
 from observation_vintage
 where country='CN' and source='WIND' and canonical_series_id in ({ph})
), agg as (
 select canonical_series_id,
        count(*) as row_count,
        count(distinct period) periods,
        min(period) first_period,
        max(period) last_period,
        count(distinct retrieved_at) retrieval_batches,
        min(retrieved_at) first_retrieved_at,
        max(retrieved_at) last_retrieved_at,
        max(vintage_no) max_vintage_no,
        count(distinct case when n_per_period>1 then period end) multi_row_periods,
        count(distinct case when n_values>1 then period end) revised_value_periods,
        sum(case when vintage_no>1 then 1 else 0 end) rows_vintage_gt1
 from base group by 1
)
select * from agg order by 1
"""
print("PROFILE")
print(con.execute(q,ids).fetchdf().to_string(index=False))
print("\nREVISION_TYPES")
print(con.execute(f"""select canonical_series_id,revision_type,pit_grade,count(*) as row_count
from observation_vintage where country='CN' and source='WIND' and canonical_series_id in ({ph})
group by 1,2,3 order by 1,2,3""",ids).fetchdf().to_string(index=False))
print("\nRELEASE_SOURCES")
print(con.execute(f"""select canonical_series_id,release_date_source,count(*) as row_count,min(available_at) min_available,max(available_at) max_available
from observation_vintage where country='CN' and source='WIND' and canonical_series_id in ({ph})
group by 1,2 order by 1,2""",ids).fetchdf().to_string(index=False))
print("\nRAW_FILES")
print(con.execute(f"""select raw_file,count(*) as row_count,min(period) min_period,max(period) max_period,
min(retrieved_at) min_retrieved,max(retrieved_at) max_retrieved
from observation_vintage where country='CN' and source='WIND' and canonical_series_id in ({ph})
group by 1 order by 1""",ids).fetchdf().to_string(index=False))
print("\nCOMPOSITE")
print(con.execute(f"""select canonical_series_id,selection_origin,source,pit_grade,
count(*) events,count(distinct period) periods,count(*)-count(distinct period) extra_events,
sum(case when valid_to is not null then 1 else 0 end) closed_events,
min(valid_from) min_valid_from,max(valid_from) max_valid_from
from read_parquet(?) where country='CN' and canonical_series_id in ({ph})
group by 1,2,3,4 order by 1,2,3,4""",[str(LONG),*ids]).fetchdf().to_string(index=False))
print("\nPERIOD_EVENT_MAX")
print(con.execute(f"""select canonical_series_id,max(n) max_events_per_period,
sum(case when n>1 then 1 else 0 end) periods_with_event_chain
from (
 select canonical_series_id,period,count(*) n
 from read_parquet(?) where country='CN' and canonical_series_id in ({ph})
 group by 1,2
) group by 1 order by 1""",[str(LONG),*ids]).fetchdf().to_string(index=False))


