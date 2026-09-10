"""Refresh strict exports and coverage after the verified 2005 activity batch."""
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

OUT = Path("reports/v2/nbs_early_2005")
PREFIX = "cn_pit_month_end_2005_20260731"


def finish():
    ingestion = json.loads((OUT / "ingestion_result.json").read_text(encoding="utf-8"))
    assert ingestion["stats"]["inserted"] == 11 and ingestion["stats"]["revisions"] == 0
    incoming = pd.read_parquet(OUT / "validated_observations.parquet")
    with duckdb.connect("macro_pit_v2.duckdb", read_only=True) as conn:
        audit = run_audit(conn, reports_dir=OUT / "audit")
        acceptance = run_acceptance(conn)
        (OUT / "acceptance.txt").write_text(acceptance.render(), encoding="utf-8")
        exports = build_monthly_wide_snapshot(conn, f"data/exports/{PREFIX}", "2005-01-31", "2026-07-31", country="CN", pit_mode="strict")
        counts = conn.sql("SELECT source,count(*) row_count FROM observation_vintage GROUP BY source ORDER BY source").df()
        china = conn.sql("SELECT count(*),count(DISTINCT canonical_series_id) FROM observation_vintage WHERE country='CN'").fetchone()
    prior_counts = pd.read_csv(OUT / "before/database_source_counts.csv").set_index("source").row_count
    difference = counts.set_index("source").row_count - prior_counts
    assert difference.loc["NBS"] == 11 and difference.drop("NBS").eq(0).all()
    counts.to_csv(OUT / "database_source_counts.csv", index=False)
    before = pd.read_csv(OUT / "before" / f"{PREFIX}_values.csv").set_index("as_of_month_end")
    values = pd.read_csv(exports["values_csv"]).set_index("as_of_month_end")
    periods = pd.read_parquet(exports["periods_parquet"])
    prior_periods = pd.read_parquet(OUT / "before" / f"{PREFIX}_periods.parquet")
    for frame in (periods, prior_periods):
        frame.as_of_month_end = frame.as_of_month_end.astype(str)
        frame.set_index("as_of_month_end", inplace=True)
    assert values.index.equals(before.index) and values.columns.equals(before.columns)
    assert values.notna().equals(periods.notna())
    vc = ~(values.eq(before) | (values.isna() & before.isna()))
    pc = ~(periods.eq(prior_periods) | (periods.isna() & prior_periods.isna()))
    expected = {(r.canonical_series_id,r.period):r for r in incoming.itertuples()}
    changes = []
    for date in values.index:
        for canonical in values.columns[(vc | pc).loc[date]]:
            row = expected[(canonical,periods.loc[date,canonical])]
            assert row.value == values.loc[date,canonical]
            assert row.available_at <= pd.Timestamp(date + " 23:59:59", tz="Asia/Shanghai")
            changes.append(dict(as_of_month_end=date, indicator=canonical, before_value=before.loc[date,canonical],
                                after_value=row.value, before_period=prior_periods.loc[date,canonical], after_period=row.period,
                                value_changed=bool(vc.loc[date,canonical]), period_changed=bool(pc.loc[date,canonical])))
    pd.DataFrame(changes).to_csv(OUT / "export_changes.csv", index=False, encoding="utf-8-sig")
    for name in ("audit.html", "cn_coverage.csv", "us_coverage.csv", "global_coverage.csv"):
        shutil.copyfile(OUT / "audit" / name, Path("reports/v2") / name)
    helper = runpy.run_path("scripts/finalize_nbs_economy_batch.py")
    execute = runpy.run_path("scripts/run_nbs_price_batch_once.py")["execute_notebook"]
    history_py = Path("reports/v2/pit_csv_inspection/field_history_review.py")
    history_nb = history_py.with_suffix(".ipynb")
    cells = [helper["code_cell"](s.lstrip()) for s in history_py.read_text(encoding="utf-8").split("# %%") if s.strip()]
    history_nb.write_text(json.dumps(helper["notebook"](cells), ensure_ascii=False, indent=2), encoding="utf-8")
    execute(history_nb)
    execute(Path("reports/v2/pit_csv_inspection/review.ipynb"))
    history = pd.read_csv("reports/v2/pit_csv_inspection/field_history.csv")
    previous = pd.read_csv(OUT / "before/field_history.csv")
    comparison = history.merge(previous, on="indicator", suffixes=("_after", "_before"))
    comparison = comparison[comparison.indicator.isin(incoming.canonical_series_id)].copy()
    comparison["new_strict_periods"] = comparison.strict_periods_by_cutoff_after-comparison.strict_periods_by_cutoff_before
    assert comparison.new_strict_periods.sum() == 11
    assert comparison.strict_first_period_by_cutoff_after.eq("2005-01").all()
    columns = ["indicator", "name_after", "strict_first_period_by_cutoff_before", "strict_first_period_by_cutoff_after",
               "strict_periods_by_cutoff_before", "strict_periods_by_cutoff_after", "first_nonnull_as_of_before",
               "first_nonnull_as_of_after", "max_source_age_months_after", "new_strict_periods"]
    comparison[columns].to_csv(OUT / "field_coverage_changes.csv", index=False, encoding="utf-8-sig")
    runpy.run_path("scripts/plan_history_from_2005.py")["build"]()
    code = helper["code_cell"]
    nb = OUT / "review.ipynb"
    cells = [dict(cell_type="markdown", metadata={}, source=["# 2005 年早期工业与社零核验\n", "只读查看已核验的原值、真实发布时间与缺口。\n"]),
             code("from pathlib import Path\nimport os, json, pandas as pd\nroot=next(p for p in [Path.cwd(),*Path.cwd().parents] if (p/'macro_pit_v2.duckdb').exists())\nos.chdir(root)\nout=Path('reports/v2/nbs_early_2005')\nsamples=pd.read_csv(out/'validated_samples.csv')\nassert len(samples)==11 and samples.result.eq('PASS').all()\nassert not samples.duplicated(['canonical_series_id','period']).any()\nsamples[['period','canonical_series_id','value','release_at','raw_sha256']]\n"),
             code("samples.pivot(index='period',columns='canonical_series_id',values='value')\n"),
             code("coverage=pd.read_csv(out/'field_coverage_changes.csv')\nassert coverage.new_strict_periods.sum()==11\ncoverage\n"),
             code("excluded=pd.read_csv(out/'excluded_articles.csv')\nassert len(excluded)==1 and excluded.reason.eq('YTD_only_no_explicit_monthly_value').all()\nexcluded\n")]
    nb.write_text(json.dumps(helper["notebook"](cells), ensure_ascii=False, indent=2), encoding="utf-8")
    execute(nb)
    paths = [nb, history_nb, Path("reports/v2/pit_csv_inspection/review.ipynb")]
    nb_counts = {str(p):sum(c['cell_type']=='code' for c in json.loads(p.read_text(encoding='utf-8'))['cells']) for p in paths}
    (OUT / "notebook_execution.json").write_text(json.dumps(dict(status="PASS", code_cells=nb_counts), indent=2), encoding="utf-8")
    result = dict(status="COMPLETE", at=datetime.now(SHANGHAI).isoformat(), database_rows=int(counts.row_count.sum()),
                  china_rows=china[0], china_series=china[1], nbs_rows=int(counts.set_index("source").loc["NBS","row_count"]),
                  inserted=11, revisions=0, wide_rows=len(values), wide_indicators=len(values.columns),
                  before_missing_pct=round(before.isna().to_numpy().mean()*100,2),
                  after_missing_pct=round(values.isna().to_numpy().mean()*100,2),
                  changed_cells=len(changes), changed_value_cells=int(vc.to_numpy().sum()), changed_period_cells=int(pc.to_numpy().sum()),
                  newly_nonnull_cells=int((before.isna() & values.notna()).to_numpy().sum()),
                  acceptance_passed=acceptance.passed, acceptance_failures=[asdict(c) for c in acceptance.checks if not c.passed],
                  audit=asdict(audit), next_batch_started=False, next_search_manifest="config/nbs_early_2005_next_search_jobs.json",
                  exports={k:str(v) for k,v in exports.items()})
    (OUT / "final_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("data/history_backfill/nbs_early_2005_run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in {"audit", "exports"}}, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    finish()
