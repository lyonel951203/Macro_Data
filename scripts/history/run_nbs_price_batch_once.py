"""Run a fixed price manifest, verify all evidence, ingest, export, and exit."""
import argparse
import ast
import contextlib
from dataclasses import asdict
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from macro_pit.archive import RawArtifact
from macro_pit.db import get_connection, record_crawl_events
from macro_pit.errors import CrawlSafetyError
from macro_pit.nbs_price_review import review_price_article, search_expectation
from macro_pit.pipeline import _validate_manifest
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import SHANGHAI, ensure_aware


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def execute_notebook(path):
    notebook = json.loads(path.read_text(encoding="utf-8"))
    namespace = {"__name__": "__main__"}
    count = 0
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        tree = ast.parse("".join(cell["source"]))
        expression = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(compile(tree, str(path), "exec"), namespace)
            if expression:
                value = eval(compile(ast.Expression(expression.value), str(path), "eval"), namespace)
                if value is not None:
                    print(repr(value))
        count += 1
        cell["execution_count"] = count
        cell["outputs"] = [{"output_type": "stream", "name": "stdout", "text": output.getvalue()}]
    save_json(path, notebook)


def refresh_status(path, marker, run):
    if not marker:
        return
    current = path.read_text(encoding="utf-8")
    start, end = f"<!-- {marker}:start -->", f"<!-- {marker}:end -->"
    if current.count(start) != 1 or current.count(end) != 1:
        raise ValueError("STATUS marker missing or not unique")
    lines = [start, f"- 状态：`{run['status']}`；PID：{run['pid']}；更新时间：{run['updated_at']}。",
             f"- 固定队列 {run['queue_size']} 篇；已通过独立正文核对 {run.get('reviewed', 0)} 篇。",
             f"- 阶段：`{run.get('stage', 'starting')}`；结果：`{run['result_path']}`。"]
    if run.get("ingestion"):
        stats = run["ingestion"]
        lines.append(f"- 本批入库：新增 {stats['inserted']}、修订 {stats['revisions']}、未变 {stats['unchanged']}。")
    else:
        lines.append("- 本批尚未完成入库；当前 CSV 仍对应此前已入库快照。")
    if run.get("export_summary"):
        result = run["export_summary"]
        lines.append(f"- 主库 {result['database_rows']} 条；中国 {result['china_rows']} 条、{result['china_series']} 序列；严格宽表 {result['wide_rows']} 行 × {result['wide_indicators']} 指标。")
        lines.append(f"- 全量验收：{'PASS' if result['acceptance_passed'] else 'FAIL'}；报告：`{run['output_dir']}/review.html`。")
    if run.get("field_summary"):
        summary = run["field_summary"]
        prices = summary["price_coverage"]
        lines.append(f"- 截止日前原始月份：CPI {prices[0]['observed_source_months']}、PPI {prices[1]['observed_source_months']}；CSV 空值率 {summary['missing_pct']}%。")
    if run.get("error"):
        lines.append(f"- 已停止：{run['error']}")
    lines.append(end)
    a, b = current.index(start), current.index(end) + len(end)
    if path.read_text(encoding="utf-8") != current:
        raise RuntimeError("STATUS changed during refresh; result JSON is authoritative")
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text(current[:a] + "\n".join(lines) + current[b:], encoding="utf-8")
    os.replace(temporary, path)


def run_batch(manifest_path, batch, *, allow_network=False, review_only=False, status_marker=None):
    if not re.fullmatch(r"nbs_[a-z0-9_]{1,60}", batch):
        raise ValueError("Invalid batch name")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest["items"]
    if not 1 <= len(items) <= 25 or len({i['url'] for i in items}) != len(items):
        raise ValueError("Fixed manifest must contain 1..25 distinct URLs")
    # Check every archived search record before any network access.
    for item in items:
        search_expectation(item)
    out = Path("reports/v2") / batch
    out.mkdir(parents=True, exist_ok=True)
    state_path = Path("data/history_backfill") / f"{batch}_validation_state.json"
    result_path = Path("data/history_backfill") / f"{batch}_run.json"
    expected_path = Path("config") / f"{batch}_expected.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"items": {}}
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if state.get("manifest_sha256", digest) != digest:
        raise ValueError("Manifest changed since checkpoint")
    state["manifest_sha256"] = digest
    run = {"status": "RUNNING", "stage": "reviewing", "pid": os.getpid(), "queue_size": len(items),
           "started_at": datetime.now(SHANGHAI).isoformat(), "reviewed": 0,
           "result_path": result_path.as_posix(), "output_dir": out.as_posix(), "review_only": review_only}
    previous = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
    if previous and previous.get("review_only", review_only) != review_only:
        raise ValueError("Cannot change review-only mode for an existing batch")
    if previous.get("status") == "COMPLETE":
        return previous
    if previous.get("ingestion"):
        run["ingestion"] = previous["ingestion"]
    lock = Path("data/history_backfill/nbs_price_batch.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("x", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "batch": batch}, handle)
    source = None

    def checkpoint():
        run["updated_at"] = datetime.now(SHANGHAI).isoformat()
        state["status"] = run["status"]
        state["pending"] = len(items) - len(state["items"])
        save_json(state_path, state)
        save_json(result_path, run)
        refresh_status(Path("reports/v2/STATUS.md"), status_marker, run)

    def command(script, *args):
        subprocess.run([sys.executable, script, *map(str, args)], check=True)

    try:
        checkpoint()
        source = NBSSource(allow_network=allow_network)
        _validate_manifest([i["url"] for i in items], source.policy)
        if not review_only:
            before = out / "before"
            before.mkdir(exist_ok=True)
            for path in Path("data/exports").glob("cn_pit_month_end_2005_20260731*"):
                if not (before / path.name).exists():
                    shutil.copyfile(path, before / path.name)
        expected = {}
        for item in items:
            url = item["url"]
            run["current_url"] = url
            offset = len(source.client.events)
            try:
                if url in state["items"]:
                    stored = dict(state["items"][url]["artifact"])
                    stored["retrieved_at"] = ensure_aware(stored["retrieved_at"])
                    artifact = RawArtifact(**stored)
                    content = Path(artifact.path).read_bytes()
                    from_cache = True
                else:
                    fetched = source.fetch(url, refresh=False)
                    artifact, content, from_cache = fetched.artifact, fetched.content, fetched.from_cache
                review = review_price_article(item, content, artifact)
                parsed = source.parse(content, artifact)
                if len(parsed) != 1 or any(parsed[0][k] != review[k] for k in ["canonical_series_id", "period", "value", "pit_grade"]):
                    raise ValueError("Parser and independent review disagree")
                if any(parsed[0][k] != ensure_aware(review[k]) for k in ["release_at", "available_at"]):
                    raise ValueError("Parser and independently verified publication time disagree")
                expected[url] = review
                saved = asdict(artifact)
                saved["retrieved_at"] = artifact.retrieved_at.isoformat()
                state["items"][url] = {**item, "artifact": saved, "from_cache": from_cache}
                save_json(expected_path, expected)
                run["reviewed"] = len(expected)
                checkpoint()
                print(json.dumps({"reviewed": review["period"], "indicator": review["canonical_series_id"], "value": review["value"]}), flush=True)
            finally:
                if source.client.events[offset:]:
                    con = get_connection("macro_pit_v2.duckdb")
                    try:
                        record_crawl_events(con, source.client.events[offset:], parser_version="nbs_price_independent_review_v1")
                    finally:
                        con.close()
        common = ["--manifest", manifest_path, "--state-path", state_path,
                  "--expected", expected_path, "--output-dir", out]
        run["stage"] = "validating" if review_only else "ingesting"
        checkpoint()
        ingestion_path = out / "ingestion_result.json"
        # The ingestion result is written before export; preserve it on resume.
        command("scripts/validate_nbs_legacy_batch.py", *common,
                *([] if review_only or ingestion_path.exists() else ["--ingest"]))
        if not review_only:
            run["ingestion"] = json.loads(ingestion_path.read_text())["ingestion"]
            run["stage"] = "exporting"
            checkpoint()
            command("scripts/prepare_nbs_legacy_batch.py", "--coverage-only")
            command("scripts/history/finalize_nbs_legacy_batch.py", *common)
            run["export_summary"] = json.loads((out / "final_result.json").read_text(encoding="utf-8"))
            command("scripts/compare_nbs_batch_exports.py", "--output-dir", out, "--expected", expected_path)
            for path in [Path("reports/v2/pit_csv_inspection/review.ipynb"),
                         Path("reports/v2/pit_csv_inspection/field_history_review.ipynb"), out / "review.ipynb"]:
                execute_notebook(path)
            run["field_summary"] = json.loads(Path("reports/v2/pit_csv_inspection/field_history_summary.json").read_text(encoding="utf-8"))
        run["status"] = "COMPLETE"
        run["stage"] = "review_only_complete" if review_only else "exported_and_checked"
    except Exception as exc:
        run["status"] = "BLOCKED" if isinstance(exc, CrawlSafetyError) else "FAILED"
        run["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if source:
            source.close()
        run["finished_at"] = datetime.now(SHANGHAI).isoformat()
        try:
            checkpoint()
        finally:
            lock.unlink()
    return run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--review-only", action="store_true")
    parser.add_argument("--status-marker")
    args = parser.parse_args()
    os.chdir(Path(__file__).resolve().parents[2])
    result = run_batch(args.manifest, args.batch, allow_network=args.allow_network,
                       review_only=args.review_only, status_marker=args.status_marker)
    print(json.dumps({k: v for k, v in result.items() if k not in {"export_summary", "field_summary"}}, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "COMPLETE" else 1)
