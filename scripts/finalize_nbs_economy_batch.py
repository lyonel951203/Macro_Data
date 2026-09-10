"""Refresh strict exports and reproducible evidence for the finite economy batch."""
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


OUT = Path("reports/v2/nbs_economy_batch1")
PREFIX = "cn_pit_month_end_2005_20260731"


def code_cell(source):
    return dict(cell_type="code", metadata={}, execution_count=None, outputs=[], source=source.splitlines(keepends=True))


def notebook(cells):
    return dict(cells=cells, metadata={"kernelspec":{"display_name":"Python 3","language":"python","name":"python3"}},
                nbformat=4, nbformat_minor=4)


def finish():
    ingestion=json.loads((OUT / "ingestion_result.json").read_text(encoding="utf-8"))
    assert ingestion["stats"]["inserted"]==30 and ingestion["verified_current_snapshots"]
    replay=json.loads((OUT / "replay_summary.json").read_text(encoding="utf-8"))
    assert not replay["errors"] and replay["compared_rows"]==822 and replay["unchanged_rows"]==809
    before=pd.read_csv(OUT / "before" / f"{PREFIX}_values.csv").set_index("as_of_month_end")
    before_periods=pd.read_parquet(OUT / "before" / f"{PREFIX}_periods.parquet")
    before_periods.as_of_month_end=before_periods.as_of_month_end.astype(str)
    before_periods=before_periods.set_index("as_of_month_end")
    with duckdb.connect("macro_pit_v2.duckdb",read_only=True) as conn:
        audit=run_audit(conn,reports_dir=OUT / "audit")
        acceptance=run_acceptance(conn)
        (OUT / "acceptance.txt").write_text(acceptance.render(),encoding="utf-8")
        exports=build_monthly_wide_snapshot(conn,f"data/exports/{PREFIX}","2005-01-31","2026-07-31",country="CN",pit_mode="strict")
        total=conn.sql("SELECT count(*) FROM observation_vintage").fetchone()[0]
        cn=conn.sql("SELECT count(*),count(DISTINCT canonical_series_id) FROM observation_vintage WHERE country='CN'").fetchone()
        sources=conn.sql("SELECT source,count(*) AS row_count,count(DISTINCT canonical_series_id) AS series_count FROM observation_vintage WHERE country='CN' GROUP BY source ORDER BY source").df()
    for name in ["audit.html","cn_coverage.csv","us_coverage.csv","global_coverage.csv"]:
        shutil.copyfile(OUT / "audit" / name,Path("reports/v2") / name)
    values=pd.read_csv(exports["values_csv"]).set_index("as_of_month_end")
    periods=pd.read_parquet(exports["periods_parquet"])
    periods.as_of_month_end=periods.as_of_month_end.astype(str)
    periods=periods.set_index("as_of_month_end")
    assert values.index.equals(before.index) and values.columns.equals(before.columns)
    assert values.notna().equals(periods.notna())
    value_changed=~(values.eq(before) | (values.isna() & before.isna()))
    period_changed=~(periods.eq(before_periods) | (periods.isna() & before_periods.isna()))
    reviewed=pd.read_csv(OUT / "validated_samples.csv")
    targets=set(reviewed.canonical_series_id)
    assert set(values.columns[(value_changed | period_changed).any()]).issubset(targets)
    expected={(r.canonical_series_id,r.period):r.value for r in reviewed.itertuples()}
    changes=[]
    for date in values.index:
        for indicator in values.columns[(value_changed | period_changed).loc[date]]:
            selected=periods.loc[date,indicator]
            assert expected[(indicator,selected)]==values.loc[date,indicator]
            changes.append(dict(as_of_month_end=date,canonical_series_id=indicator,
                                before_value=before.loc[date,indicator],after_value=values.loc[date,indicator],
                                before_period=before_periods.loc[date,indicator],after_period=selected,
                                value_changed=bool(value_changed.loc[date,indicator]),
                                period_changed=bool(period_changed.loc[date,indicator])))
    pd.DataFrame(changes).to_csv(OUT / "export_changes.csv",index=False,encoding="utf-8-sig")
    sources.to_csv(OUT / "china_source_counts.csv",index=False,encoding="utf-8-sig")
    ages=[]
    for date in values.index:
        for indicator in sorted(targets):
            selected=periods.loc[date,indicator]
            ages.append(dict(as_of_month_end=date,canonical_series_id=indicator,source_period=selected,
                             source_age_months=None if pd.isna(selected) else pd.Period(date,freq="M").ordinal-pd.Period(selected,freq="M").ordinal))
    pd.DataFrame(ages).to_csv(OUT / "panel_source_age.csv",index=False,encoding="utf-8-sig")
    # The field-history script is the source of truth for its notebook.
    history_py=Path("reports/v2/pit_csv_inspection/field_history_review.py")
    history_nb=history_py.with_suffix(".ipynb")
    history_nb.write_text(json.dumps(notebook([code_cell(c.lstrip()) for c in history_py.read_text(encoding="utf-8").split("# %%") if c.strip()]),ensure_ascii=False,indent=2),encoding="utf-8")
    execute=runpy.run_path("scripts/run_nbs_price_batch_once.py")["execute_notebook"]
    execute(Path("reports/v2/pit_csv_inspection/review.ipynb"))
    execute(history_nb)
    plan=runpy.run_path("scripts/plan_nbs_economy_gaps.py")["build_plan"]()
    field_summary=json.loads(Path("reports/v2/pit_csv_inspection/field_history_summary.json").read_text(encoding="utf-8"))
    history=pd.read_csv("reports/v2/pit_csv_inspection/field_history.csv")
    history[history.indicator.isin(targets)].to_csv(OUT / "affected_field_history.csv",index=False,encoding="utf-8-sig")
    summary=dict(status="FINALIZING",at=datetime.now(SHANGHAI).isoformat(), database_rows=total,
                 china_rows=cn[0],china_series=cn[1],batch=ingestion,replay=replay,audit=asdict(audit),
                 acceptance_passed=acceptance.passed,
                 acceptance_failures=[asdict(c) for c in acceptance.checks if not c.passed],
                 wide_rows=len(values),wide_indicators=len(values.columns),
                 before_missing_pct=round(before.isna().to_numpy().mean()*100,2),
                 after_missing_pct=round(values.isna().to_numpy().mean()*100,2),
                 changed_export_cells=len(changes),changed_value_cells=int(value_changed.to_numpy().sum()),
                 changed_period_cells=int(period_changed.to_numpy().sum()),
                 newly_nonnull_cells=int((before.isna() & values.notna()).to_numpy().sum()),
                 field_summary=field_summary,next_plan=plan,exports={k:str(v) for k,v in exports.items()})
    (OUT / "final_result.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    cells=[dict(cell_type="markdown",metadata={},source=["# NBS 综合稿首批复核\n","离线核对原稿、数值、发布时间、解析更正和严格 CSV。主库只读；复核证据文件会刷新。\n"]),
           code_cell("from pathlib import Path\nimport os, runpy, pandas as pd, json\nroot=next(p for p in [Path.cwd(), *Path.cwd().parents] if (p/'macro_pit_v2.duckdb').exists())\nos.chdir(root)\nresult=runpy.run_path('scripts/validate_nbs_economy_batch.py')['validate']()\nassert result['reviewed_records']==30 and result['baseline_preservation']=='PASS'\nresult\n"),
           code_cell("out=Path('reports/v2/nbs_economy_batch1')\npd.read_csv(out/'parser_correction_ledger.csv')[['canonical_series_id','period','before_value','after_value','official_statistical_revision']]\n"),
           code_cell("pd.read_csv(out/'affected_field_history.csv')[['name','strict_first_period_by_cutoff','strict_periods_by_cutoff','max_source_age_months']]\n"),
           code_cell("gaps=pd.read_csv(out/'recent_indicator_month_gaps.csv')\nassert not gaps.duplicated(['canonical_series_id','period']).any()\ngaps.groupby(['series_name','status']).size().unstack(fill_value=0)\n"),
           code_cell("changes=pd.read_csv(out/'export_changes.csv')\nsummary=json.loads((out/'final_result.json').read_text(encoding='utf-8'))\nassert len(changes)==summary['changed_export_cells']\nchanges.groupby('canonical_series_id').agg(changed_cells=('as_of_month_end','size'),first_changed=('as_of_month_end','min'))\n")]
    review=OUT / "review.ipynb"
    review.write_text(json.dumps(notebook(cells),ensure_ascii=False,indent=2),encoding="utf-8")
    execute(review)
    counts={str(p):sum(c["cell_type"]=="code" for c in json.loads(p.read_text(encoding="utf-8"))["cells"])
            for p in [review,history_nb,Path("reports/v2/pit_csv_inspection/review.ipynb")]}
    (OUT / "notebook_execution.json").write_text(json.dumps(dict(code_cells=counts,result="PASS"),indent=2),encoding="utf-8")
    summary["status"]="COMPLETE"
    summary["at"]=datetime.now(SHANGHAI).isoformat()
    (OUT / "final_result.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k not in {"audit","batch","field_summary","replay","exports"}},ensure_ascii=False,indent=2))
    return summary


if __name__=="__main__":
    finish()
