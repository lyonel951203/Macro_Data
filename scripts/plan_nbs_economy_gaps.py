"""Classify official economy gaps and save a finite next queue without network."""
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import duckdb
import pandas as pd

from macro_pit.index_discovery import CandidateUrl, write_candidates


OUT = Path("reports/v2/nbs_economy_batch1")
CUTOFF = pd.Timestamp("2026-07-31 23:59:59", tz="Asia/Shanghai")


def build_plan(*, output_dir=None, next_batch="nbs_economy_batch2"):
    out=Path(output_dir) if output_dir else OUT
    out.mkdir(parents=True,exist_ok=True)
    assert re.fullmatch(r"nbs_economy_batch[0-9]+",next_batch)
    all_candidates = pd.read_parquet(OUT / "rediscovered_all.parquet")
    extra_path=out/"additional_title_candidates.csv"
    if extra_path.exists():
        extra=pd.read_csv(extra_path)
        all_candidates=pd.concat([all_candidates,extra[all_candidates.columns]],ignore_index=True).drop_duplicates("url",keep="last")
    # Preserve the old discovery file before merging the broader title rule.
    backup = out / "before"
    backup.mkdir(exist_ok=True)
    for path in Path("data/discovery").glob("nbs_candidate*"):
        if not (backup / path.name).exists():
            shutil.copyfile(path, backup / path.name)
    candidate_records = all_candidates.astype(object).where(pd.notna(all_candidates), None).to_dict("records")
    write_candidates([CandidateUrl(**r) for r in candidate_records])
    economy = all_candidates[all_candidates.title.str.contains("国民经济|经济运行")].copy()
    excluded = economy[economy.title.str.contains("答记者问|统计公报|解读|评读|：|:")].copy()
    excluded["reason"] = "commentary_press_qa_or_annual_bulletin"
    excluded.to_csv(out / "excluded_discovery_titles.csv", index=False, encoding="utf-8-sig")
    economy = economy.drop(excluded.index)
    inventory = pd.read_csv(OUT / "cached_economy_inventory.csv")
    sample = json.loads(Path("data/history_backfill/nbs_economy_sample_batch1_state.json").read_text(encoding="utf-8"))
    combined_inventory=inventory[~inventory.title.str.contains("答记者问|：|:")]
    raw_periods = set(combined_inventory.periods.dropna()) | {r["period"] for r in sample["items"].values()}
    with duckdb.connect("macro_pit_v2.duckdb", read_only=True) as conn:
        observations = conn.sql("SELECT canonical_series_id,period,available_at,pit_grade,source_url FROM observation_vintage WHERE source='NBS'").df()
        failed = set(conn.sql("SELECT url FROM crawl_log WHERE source='NBS' QUALIFY row_number() OVER (PARTITION BY url ORDER BY completed_at DESC)=1 AND success=false").df().url)
    strict = observations[observations.pit_grade.isin(["A","B"]) & observations.available_at.le(CUTOFF)]
    keys = set(zip(strict.canonical_series_id, strict.period))
    archived = set(inventory.url) | set(observations.source_url)
    meta = pd.read_csv("data/exports/cn_pit_month_end_2005_20260731_metadata.csv")
    indicators = meta[meta.source.eq("NBS") & meta.frequency.eq("M") & ~meta.canonical_series_id.str.contains("PMI")]
    rows = []
    for item in economy.itertuples():
        soup = BeautifulSoup(Path(item.index_raw_file).read_text(encoding="utf-8"), "lxml")
        dates = set()
        for a in soup.find_all("a", href=True):
            if urljoin("https://www.stats.gov.cn/sj/zxfb/", str(a["href"])) != item.url:
                continue
            li = a.find_parent("li")
            if li:
                dates.update(re.findall(r"20\d{2}-\d{2}-\d{2}", li.get_text(" ", strip=True)))
        assert len(dates)==1, (item.url, dates)
        date = dates.pop()
        # This is a candidate queue hint ONLY. Validate historical page timestamp
        # and statistical period in the body before any later ingestion.
        candidate_period = str(pd.Period(date, freq="M")-1)
        hinted = re.search(r"(?<!\d)(\d{1,2})月份", item.title)
        if hinted:
            assert int(hinted.group(1)) == int(candidate_period[-2:])
        if pd.notna(item.period):
            assert item.period == candidate_period
        missing = [i for i in indicators.canonical_series_id if (i,candidate_period) not in keys]
        rows.append(dict(title=item.title, url=item.url, period=candidate_period,
                         index_display_date=date, period_evidence="index_display_date_previous_month_hint_only",
                         index_raw_file=item.index_raw_file, raw_archived=item.url in archived,
                         prior_fetch_failed=item.url in failed, missing_indicators=";".join(missing),
                         missing_indicator_count=len(missing)))
    candidates = pd.DataFrame(rows).sort_values("period")
    raw_periods.update(candidates.loc[candidates.raw_archived,"period"])
    candidates.to_csv(out / "economy_candidates.csv", index=False, encoding="utf-8-sig")
    # Main batch prefers 2022+ missing ordinary-month releases. Jan/Feb and
    # quarter/year-end releases still require explicit monthly-column review.
    eligible = candidates[~candidates.raw_archived & ~candidates.prior_fetch_failed &
                          candidates.period.between("2022-01", "2026-06") &
                          ~candidates.period.str.endswith("-02") & candidates.missing_indicator_count.gt(0)]
    queue = eligible.sort_values(["missing_indicator_count", "period"], ascending=[False,True]).head(20).copy()
    assert len(queue)<=20 and queue.url.is_unique
    queue.to_csv(out / "next_20_candidates.csv", index=False, encoding="utf-8-sig")
    manifest = dict(batch=next_batch, status="READY_NOT_STARTED" if len(queue) else "NO_CANDIDATES", max_articles=20,
                    policy="Official archived index candidates only; validate body values, monthly/YTD definitions and historical timestamp before ingestion. Never derive PIT from URL or index hint.",
                    items=queue[["title","url","period","index_raw_file"]].to_dict("records"))
    manifest_path=Path("config")/f"{next_batch}_candidates.json"
    encoded=json.dumps(manifest,ensure_ascii=False,indent=2)
    if Path(f"data/history_backfill/{next_batch}_download_state.json").exists() and manifest_path.read_text(encoding="utf-8")!=encoded:
        raise RuntimeError("Cannot replace a manifest whose download has started; choose a new batch name")
    manifest_path.write_text(encoded,encoding="utf-8")
    grid=[]
    for period in map(str,pd.period_range("2022-01","2026-06",freq="M")):
        urls = candidates[candidates.period.eq(period)].url.tolist()
        for spec in indicators.itertuples():
            if (spec.canonical_series_id,period) in keys:
                status="covered_strict"
            elif period[-2:] in {"01","02"} and spec.canonical_series_id not in {"CN_CPI_YOY","CN_PPI_YOY"}:
                status="jan_feb_publication_structure_needs_review"
            elif period in raw_periods:
                status=("archived_sales_definition_needs_review" if "NEW_HOME_SALES" in spec.canonical_series_id and period < "2024-01"
                        else "archived_combined_article_indicator_absent")
            elif urls:
                status="candidate_exists_article_not_archived"
            else:
                status="combined_release_candidate_not_discovered"
            grid.append(dict(canonical_series_id=spec.canonical_series_id,series_name=spec.series_name,
                             period=period,status=status,candidate_urls=";".join(urls)))
    gaps=pd.DataFrame(grid)
    gaps.to_csv(out / "recent_indicator_month_gaps.csv",index=False,encoding="utf-8-sig")
    result=dict(discovered_candidates=len(all_candidates), economy_candidates=len(candidates),
                excluded_economy_titles=len(excluded), next_queue=len(queue), next_queue_status=manifest["status"],
                reference_window="2022-01..2026-06", gap_cells=len(gaps), gap_status_counts=gaps.status.value_counts().to_dict())
    (out / "gap_plan_summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=="__main__":
    build_plan()
