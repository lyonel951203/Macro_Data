"""Run a bounded, reviewed list of date-window searches with one polite client."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from macro_pit.config import source_policy
from macro_pit.http import PoliteHttpClient
from macro_pit.nbs_search import discover_nbs_legacy
from macro_pit.timeutils import SHANGHAI


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--max-pages-per-job", type=int, default=1)
parser.add_argument("--allow-network", action="store_true")
parser.add_argument("--job-manifest", default="config/nbs_gap_search_jobs.json")
parser.add_argument("--result-path", default="data/history_backfill/nbs_gap_search_run.json")
parser.add_argument("--status-marker", default=None, help="Update an existing marked block in STATUS.md")
args = parser.parse_args()
if not 1 <= args.max_pages_per_job <= 3:
    parser.error("max-pages-per-job must be 1..3")
os.chdir(Path(__file__).resolve().parents[1])
jobs = json.loads(Path(args.job_manifest).read_text(encoding="utf-8"))["jobs"]
if not 1 <= len(jobs) <= 5:
    raise ValueError("reviewed search manifest must contain 1..5 date windows")
for job in jobs:
    if not 1 <= int(job.get("max_network_pages", args.max_pages_per_job)) <= args.max_pages_per_job:
        raise ValueError("per-job page limit must fit --max-pages-per-job")

result_path = Path(args.result_path)
run = {"status": "RUNNING", "pid": os.getpid(), "started_at": datetime.now(SHANGHAI).isoformat(),
       "max_new_search_pages": sum(int(j.get("max_network_pages", args.max_pages_per_job)) for j in jobs),
       "job_manifest": args.job_manifest, "jobs": []}

def save_run():
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, result_path)

save_run()
try:
    with PoliteHttpClient(source="NBS", policy=source_policy("NBS"), allow_network=args.allow_network) as client:
        for job in jobs:
            run["current_job"] = job["name"]
            save_run()
            state = discover_nbs_legacy(
                "macro_pit_v2.duckdb", terms=[job["term"]], start_date=job["start_date"],
                end_date=job["end_date"], state_path=f"data/history_backfill/nbs_{job['name']}_search_state.json",
                output_dir="data/discovery/nbs_legacy", allow_network=args.allow_network,
                max_network_pages=int(job.get("max_network_pages", args.max_pages_per_job)), client=client,
            )
            summary = {"job": job["name"], "status": state["status"], "pages": state.get("network_pages"),
                       "candidates": state.get("candidate_rows"), "items": state["items"]}
            run["jobs"].append(summary)
            save_run()
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            if state["status"] == "BLOCKED" or (state.get("last_error") and "budget exhausted" in state["last_error"]):
                run["status"] = "BLOCKED" if state["status"] == "BLOCKED" else "BUDGET_PAUSED"
                run["error"] = state.get("last_error") or f"Search {state['status']}: {job['name']}"
                break
        else:
            run["status"] = "FINISHED"  # The bounded batch ended; individual search windows may remain PAUSED.
except Exception as exc:
    run["status"] = "FAILED"
    run["error"] = f"{type(exc).__name__}: {exc}"
finally:
    run["finished_at"] = datetime.now(SHANGHAI).isoformat()
    save_run()

try:
    subprocess.run([sys.executable, "scripts/prepare_nbs_legacy_batch.py", "--coverage-only"], check=True)
    import pandas as pd
    run["merged_candidates"] = len(pd.read_parquet("data/discovery/nbs_legacy/nbs_candidates.parquet"))
    save_run()
    if args.status_marker:
        path = Path("reports/v2/STATUS.md")
        current = path.read_text(encoding="utf-8")
        start, end = f"<!-- {args.status_marker}:start -->", f"<!-- {args.status_marker}:end -->"
        if current.count(start) != 1 or current.count(end) != 1:
            raise ValueError("STATUS.md marker is missing or not unique")
        lines = [start, f"- 后台批次状态：`{run['status']}`；结束时间：{run['finished_at']}。",
                 f"- 最新合并候选：{run['merged_candidates']} 篇。此次只发现候选，主库 observation 和严格宽表未新增。",
                 f"- 批次结果：`{result_path.as_posix()}`；`FINISHED` 仅表示本批次结束，不表示历史覆盖完整。"]
        for job in run["jobs"]:
            detail = next(iter(job["items"].values()))
            lines.append(f"- `{job['job']}`：{detail.get('last_page', 0)}/{detail.get('total_pages', '?')} 页；{job['status']}；下一页 {detail.get('next_page', 1)}。")
        if run.get("error"):
            lines.append(f"- 错误：{run['error']}")
        lines.append(end)
        a, b = current.index(start), current.index(end) + len(end)
        updated = current[:a] + "\n".join(lines) + current[b:]
        # Re-read to avoid replacing a document changed since this refresh began.
        if path.read_text(encoding="utf-8") != current:
            raise RuntimeError("STATUS.md changed during refresh; result JSON is authoritative")
        temporary = path.with_suffix(".md.tmp")
        temporary.write_text(updated, encoding="utf-8")
        os.replace(temporary, path)
except Exception as exc:
    run["postprocess_error"] = f"{type(exc).__name__}: {exc}"
    save_run()
    raise
if run["status"] != "FINISHED":
    raise SystemExit(1)
