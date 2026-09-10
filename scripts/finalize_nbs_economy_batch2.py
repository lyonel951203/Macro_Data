"""Export and audit the verified second economy batch without network requests."""
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import runpy
import shutil

import duckdb
import pandas as pd
from macro_pit.acceptance import run_acceptance
from macro_pit.audit import run_audit
from macro_pit.snapshot import build_monthly_wide_snapshot
from macro_pit.timeutils import SHANGHAI

OUT=Path("reports/v2/nbs_economy_batch2")
PREFIX="cn_pit_month_end_2005_20260731"


def finish():
    ingest=json.loads((OUT/"ingestion_result.json").read_text(encoding="utf-8"))
    regression=json.loads((OUT/"regression_result.json").read_text(encoding="utf-8"))
    assert ingest["stats"]["inserted"]==206 and ingest["stats"]["revisions"]==0
    assert regression["status"]=="PASS"
    with duckdb.connect("macro_pit_v2.duckdb",read_only=True) as conn:
        audit=run_audit(conn,reports_dir=OUT/"audit")
        acceptance=run_acceptance(conn)
        (OUT/"acceptance.txt").write_text(acceptance.render(),encoding="utf-8")
        exports=build_monthly_wide_snapshot(conn,f"data/exports/{PREFIX}","2005-01-31","2026-07-31",country="CN",pit_mode="strict")
        count=conn.sql("SELECT count(*) FROM observation_vintage").fetchone()[0]
        cn=conn.sql("SELECT count(*),count(DISTINCT canonical_series_id) FROM observation_vintage WHERE country='CN'").fetchone()
        source_counts=conn.sql("SELECT source,count(*) row_count FROM observation_vintage GROUP BY source ORDER BY source").df()
    prior_counts=pd.read_csv(OUT/"before/database_source_counts.csv").set_index("source").row_count
    difference=source_counts.set_index("source").row_count-prior_counts
    assert difference.loc["NBS"]==206 and difference.drop("NBS").eq(0).all()
    source_counts.to_csv(OUT/"database_source_counts.csv",index=False)
    for name in ["audit.html","cn_coverage.csv","us_coverage.csv","global_coverage.csv"]:
        shutil.copyfile(OUT/"audit"/name,Path("reports/v2")/name)
    before=pd.read_csv(OUT/"before"/f"{PREFIX}_values.csv").set_index("as_of_month_end")
    values=pd.read_csv(exports["values_csv"]).set_index("as_of_month_end")
    periods=pd.read_parquet(exports["periods_parquet"])
    before_periods=pd.read_parquet(OUT/"before"/f"{PREFIX}_periods.parquet")
    for frame in [periods,before_periods]: frame.as_of_month_end=frame.as_of_month_end.astype(str)
    periods=periods.set_index("as_of_month_end"); before_periods=before_periods.set_index("as_of_month_end")
    assert before.index.equals(values.index) and before.columns.equals(values.columns)
    assert values.notna().equals(periods.notna())
    vc=~(values.eq(before) | (values.isna() & before.isna()))
    pc=~(periods.eq(before_periods) | (periods.isna() & before_periods.isna()))
    incoming=pd.read_parquet(OUT/"validated_observations.parquet")
    expected={(r.canonical_series_id,r.period):r.value for r in incoming.itertuples()}
    changed=[]
    for date in values.index:
        for indicator in values.columns[(vc|pc).loc[date]]:
            selected=periods.loc[date,indicator]
            assert expected[(indicator,selected)]==values.loc[date,indicator]
            changed.append(dict(as_of_month_end=date,canonical_series_id=indicator,
                                before_value=before.loc[date,indicator],after_value=values.loc[date,indicator],
                                before_period=before_periods.loc[date,indicator],after_period=selected,
                                value_changed=bool(vc.loc[date,indicator]),period_changed=bool(pc.loc[date,indicator])))
    pd.DataFrame(changed).to_csv(OUT/"export_changes.csv",index=False,encoding="utf-8-sig")
    helper=runpy.run_path("scripts/finalize_nbs_economy_batch.py")
    execute=runpy.run_path("scripts/run_nbs_price_batch_once.py")["execute_notebook"]
    history_py=Path("reports/v2/pit_csv_inspection/field_history_review.py")
    history_nb=history_py.with_suffix(".ipynb")
    cells=[helper["code_cell"](c.lstrip()) for c in history_py.read_text(encoding="utf-8").split("# %%") if c.strip()]
    history_nb.write_text(json.dumps(helper["notebook"](cells),ensure_ascii=False,indent=2),encoding="utf-8")
    execute(Path("reports/v2/pit_csv_inspection/review.ipynb"))
    execute(history_nb)
    current=pd.read_csv("reports/v2/pit_csv_inspection/field_history.csv")
    before_history=pd.read_csv(OUT/"before/field_history.csv")
    compare=current.merge(before_history,on="indicator",suffixes=("_after","_before"))
    compare=compare[compare.indicator.isin(incoming.canonical_series_id)].copy()
    compare["new_strict_periods"]=compare.strict_periods_by_cutoff_after-compare.strict_periods_by_cutoff_before
    assert int(compare.new_strict_periods.sum())==206
    columns=["indicator","name_after","strict_periods_by_cutoff_before","strict_periods_by_cutoff_after",
             "strict_first_period_by_cutoff_before","strict_first_period_by_cutoff_after",
             "first_nonnull_as_of_before","first_nonnull_as_of_after","max_source_age_months_before","max_source_age_months_after","new_strict_periods"]
    compare[columns].to_csv(OUT/"field_coverage_changes.csv",index=False,encoding="utf-8-sig")
    ages=[]
    for date in periods.index:
        for indicator in incoming.canonical_series_id.unique():
            selected=periods.loc[date,indicator]
            ages.append(dict(as_of_month_end=date,canonical_series_id=indicator,source_period=selected,
                             source_age_months=None if pd.isna(selected) else pd.Period(date,freq="M").ordinal-pd.Period(selected,freq="M").ordinal))
    pd.DataFrame(ages).to_csv(OUT/"panel_source_age.csv",index=False,encoding="utf-8-sig")
    plan=runpy.run_path("scripts/plan_nbs_economy_gaps.py")["build_plan"](output_dir=OUT,next_batch="nbs_economy_batch3")
    prior_gaps=pd.read_csv("reports/v2/nbs_economy_batch1/recent_indicator_month_gaps.csv")
    new_gaps=pd.read_csv(OUT/"recent_indicator_month_gaps.csv")
    merged=prior_gaps.merge(new_gaps,on=["canonical_series_id","period"],suffixes=("_before","_after"))
    assert len(merged)==len(prior_gaps) and sum(merged.status_after.eq("covered_strict"))-sum(merged.status_before.eq("covered_strict"))==206
    merged[merged.status_before.ne(merged.status_after)].to_csv(OUT/"gap_status_changes.csv",index=False,encoding="utf-8-sig")
    result=dict(status="FINALIZING",at=datetime.now(SHANGHAI).isoformat(),database_rows=count,china_rows=cn[0],china_series=cn[1],
                nbs_rows=int(source_counts.set_index("source").loc["NBS","row_count"]),ingestion=ingest,regression=regression,audit=asdict(audit),
                acceptance_passed=acceptance.passed,acceptance_failures=[asdict(c) for c in acceptance.checks if not c.passed],
                wide_rows=len(values),wide_indicators=len(values.columns),before_missing_pct=round(before.isna().to_numpy().mean()*100,2),
                after_missing_pct=round(values.isna().to_numpy().mean()*100,2),changed_export_cells=len(changed),
                changed_value_cells=int(vc.to_numpy().sum()),changed_period_cells=int(pc.to_numpy().sum()),
                newly_nonnull_cells=int((before.isna() & values.notna()).to_numpy().sum()),next_plan=plan,
                exports={k:str(v) for k,v in exports.items()})
    (OUT/"final_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    cell=helper["code_cell"]
    cells=[dict(cell_type="markdown",metadata={},source=["# NBS 综合稿第二批复核\n","离线复核 20 篇新下载稿与三篇旧稿的销售数据。不会联网或写主库；会刷新本批核验证据文件。\n"]),
           cell("from pathlib import Path\nimport os, runpy, pandas as pd, json\nroot=next(p for p in [Path.cwd(),*Path.cwd().parents] if (p/'macro_pit_v2.duckdb').exists())\nos.chdir(root)\nreview=runpy.run_path('scripts/review_nbs_economy_batch2.py')['review']()\nassert review['new_series_periods']==206\nreview\n"),
           cell("out=Path('reports/v2/nbs_economy_batch2')\nevidence=pd.read_csv(out/'validated_samples.csv')\nassert len(evidence)==246 and evidence.result.eq('PASS').all()\nevidence.groupby(['canonical_series_id','action']).size().unstack(fill_value=0)\n"),
           cell("pd.read_csv(out/'field_coverage_changes.csv')[['name_after','strict_periods_by_cutoff_before','strict_periods_by_cutoff_after','strict_first_period_by_cutoff_after']]\n"),
           cell("gaps=pd.read_csv(out/'recent_indicator_month_gaps.csv')\nassert len(gaps)==648 and not gaps.duplicated(['canonical_series_id','period']).any()\ngaps.groupby(['series_name','status']).size().unstack(fill_value=0)\n"),
           cell("changes=pd.read_csv(out/'export_changes.csv')\nchanges.groupby('canonical_series_id').agg(changed_month_ends=('as_of_month_end','size'),first_changed=('as_of_month_end','min'))\n")]
    nb=OUT/"review.ipynb"
    nb.write_text(json.dumps(helper["notebook"](cells),ensure_ascii=False,indent=2),encoding="utf-8")
    execute(nb)
    paths=[nb,history_nb,Path("reports/v2/pit_csv_inspection/review.ipynb")]
    counts={str(p):sum(c['cell_type']=='code' for c in json.loads(p.read_text(encoding='utf-8'))['cells']) for p in paths}
    (OUT/"notebook_execution.json").write_text(json.dumps(dict(status="PASS",code_cells=counts),indent=2),encoding="utf-8")
    result.update(status="COMPLETE",at=datetime.now(SHANGHAI).isoformat())
    (OUT/"final_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in {"ingestion","regression","audit","exports"}},ensure_ascii=False,indent=2))
    return result


if __name__=='__main__': finish()
