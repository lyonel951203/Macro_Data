"""Offline audit, acceptance, strict exports, and a reproducible review notebook."""
from dataclasses import asdict
import argparse
from datetime import datetime
import html
import json
import os
import shutil
from pathlib import Path

import duckdb
import pandas as pd
from macro_pit.acceptance import run_acceptance
from macro_pit.audit import run_audit
from macro_pit.snapshot import build_monthly_wide_snapshot
from macro_pit.timeutils import SHANGHAI


root = Path(__file__).resolve().parents[1]
os.chdir(root)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output-dir", default="reports/v2/nbs_legacy")
parser.add_argument("--manifest", default="config/nbs_legacy_validation_batch.json")
parser.add_argument("--state-path", default="data/history_backfill/nbs_legacy_validation_state.json")
parser.add_argument("--expected", default="config/nbs_legacy_review_expected.json")
args = parser.parse_args()
out = Path(args.output_dir)
candidate_dir = Path("reports/v2/nbs_legacy")
if out != candidate_dir:
    for name in ["candidate_month_coverage.csv", "candidate_year_coverage.csv", "candidate_missing_months.csv"]:
        shutil.copyfile(candidate_dir / name, out / name)
validation = json.loads((out / "ingestion_result.json").read_text(encoding="utf-8"))
conn = duckdb.connect("macro_pit_v2.duckdb", read_only=True)
try:
    audit = run_audit(conn, reports_dir="reports/v2")
    acceptance = run_acceptance(conn)
    (out / "acceptance.txt").write_text(acceptance.render(), encoding="utf-8")
    exports = build_monthly_wide_snapshot(
        conn, "data/exports/cn_pit_month_end_2005_20260731", "2005-01-31", "2026-07-31",
        country="CN", pit_mode="strict",
    )
    count = conn.sql("select count(*) from observation_vintage").fetchone()[0]
    cn = conn.sql("select count(*), count(distinct canonical_series_id) from observation_vintage where country='CN'").fetchone()
    old = conn.sql("select canonical_series_id, count(*) row_count, count(distinct period) periods, min(period) first_period, max(period) last_period from observation_vintage where source='NBS' and period < '2020-01' group by canonical_series_id").df()
finally:
    conn.close()
values = pd.read_parquet(exports["values_parquet"])
periods = pd.read_parquet(exports["periods_parquet"])
age_rows = []
for record in periods.to_dict("records"):
    as_of = pd.Period(record["as_of_month_end"], freq="M")
    for series in ["CN_CPI_YOY", "CN_PPI_YOY"]:
        period = record.get(series)
        age_rows.append({"as_of_month_end": str(record["as_of_month_end"]), "series": series,
                         "source_period": period, "age_months": None if pd.isna(period) else as_of.ordinal - pd.Period(period, freq="M").ordinal})
pd.DataFrame(age_rows).to_csv(out / "price_panel_source_age.csv", index=False, encoding="utf-8-sig")
summary = {"at": datetime.now(SHANGHAI).isoformat(), "database_rows": count, "china_rows": cn[0],
           "china_series": cn[1], "legacy_nbs": old.to_dict("records"), "batch": validation,
           "audit": asdict(audit), "acceptance_passed": acceptance.passed,
           "acceptance_failures": [asdict(c) for c in acceptance.checks if not c.passed],
           "wide_rows": len(values), "wide_indicators": len(values.columns) - 1,
           "exports": {k: str(v) for k,v in exports.items()}}
(out / "final_result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
sample = pd.read_csv(out / "validated_samples.csv")
coverage = pd.read_csv(out / "candidate_month_coverage.csv")
verified = {(row.canonical_series_id.split("_")[1], row.period) for row in sample.itertuples()}
coverage["body_verified"] = [row.body_verified or (row.family, row.period) in verified for row in coverage.itertuples()]
coverage.to_csv(out / "candidate_month_coverage.csv", index=False, encoding="utf-8-sig")
years = pd.read_csv(out / "candidate_year_coverage.csv")
checks = pd.DataFrame([asdict(c) for c in audit.checks])
html_report = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>NBS 旧稿批次验证</title>
<style>body{{font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif;max-width:1200px;margin:40px auto;padding:0 24px;color:#182333}}h1,h2{{color:#153e63}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:9px;border-bottom:1px solid #ddd;text-align:left}}th{{background:#edf3f8}}.scroll{{overflow:auto}}pre{{white-space:pre-wrap;background:#f5f7fa;padding:16px}}a{{color:#155a91}}</style>
<h1>NBS 旧稿批次验证</h1><p>更新时间：{html.escape(summary['at'])}。主库 macro_pit_v2.duckdb。</p>
<p>已逐篇核对 {len(sample)} 篇旧稿的正文数值、数据期和历史发布时间；原始文件 SHA256、发布边界和重复入库检查通过。</p>
<p>粒度：候选表按 URL；验证与入库按指标、数据期、vintage；严格宽表按月末、指标。</p>
<h2>正文抽验与入库证据</h2><div class="scroll">{sample[['canonical_series_id','period','value','pit_grade','release_at','result','url']].to_html(index=False,render_links=True)}</div>
<h2>搜索覆盖仍不完整</h2><p>此前 CPI 广泛搜索的第 26 页重复第 1 页，已标记 needs_narrowing，并加入重复页检测。当前按日期窗口补查缺口，进度见下表及缺月清单。候选月份来自搜索标题与日期推断，不能代替正文验证。</p>
<div class="scroll">{years.to_html(index=False)}</div>
<h2>严格宽表的使用边界</h2><p>已更新 259 个自然月末的 values、来源数据期及指标元数据文件。历史样本稀疏时，宽表中的“最新已知值”可能陈旧；非空单元格不表示该数据月已回填。请联合来源数据期使用，见 price_panel_source_age.csv。</p>
<h2>全量验收</h2><pre>{html.escape(acceptance.render())}</pre>
<h2>技术审计</h2><div class="scroll">{checks.to_html(index=False)}</div>
<h2>复核入口</h2><p><a href="validated_samples.csv">逐篇验证与 raw 路径</a> · <a href="candidate_missing_months.csv">候选缺月</a> · <a href="review.ipynb">可复跑 notebook</a> · <a href="final_result.json">完整结果</a></p>
</html>'''
(out / "review.html").write_text(html_report, encoding="utf-8")
cells = [
    {"cell_type": "markdown", "metadata": {}, "source": ["# NBS 旧稿批次复核\n", "离线复核原始文件、独立核对预期值、发布时间和候选月份缺口。不会写入主库或联网。\n"]},
    {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
        "from pathlib import Path\nimport os, sys, subprocess, pandas as pd, duckdb\n",
        "root = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / 'macro_pit_v2.duckdb').exists())\n",
        "os.chdir(root)\nenv = dict(os.environ, PYTHONPATH=str(root / 'src'), PYTHONIOENCODING='utf-8')\n",
        "subprocess.run([sys.executable, 'scripts/validate_nbs_legacy_batch.py', " + ", ".join(repr(v) for v in ["--manifest", args.manifest, "--state-path", args.state_path, "--expected", args.expected, "--output-dir", args.output_dir]) + "], env=env, check=True)\n"]},
    {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
        f"out = root / {args.output_dir!r}\n",
        "pd.read_csv(out / 'validated_samples.csv')[['canonical_series_id','period','value','release_at','pit_grade','result']]\n"]},
    {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
        "coverage = pd.read_csv(out / 'candidate_month_coverage.csv')\n",
        "coverage[coverage.candidate_urls.eq(0)]\n"]},
    {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
        "with duckdb.connect(str(root / 'macro_pit_v2.duckdb'), read_only=True) as conn:\n",
        "    legacy = conn.sql(\"SELECT canonical_series_id, period, value, release_at, available_at, pit_grade, raw_file FROM observation_vintage WHERE source='NBS' AND period < '2020-01' ORDER BY period, canonical_series_id\").df()\n",
        "legacy\n"]},
    {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
        "pd.read_csv(out / 'price_panel_source_age.csv').query('age_months > 2')\n"]},
]
(out / "review.ipynb").write_text(json.dumps({"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}, "nbformat": 4, "nbformat_minor": 4}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k:v for k,v in summary.items() if k not in {"audit","exports"}}, ensure_ascii=False))
