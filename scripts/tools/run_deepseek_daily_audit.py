"""Run only the DeepSeek audit for an existing daily update report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from macro_pit.semantic_audit import run_semantic_audit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_daily_web_update import DEFAULT_CONFIG, ROOT, load_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--daily-report")
    parser.add_argument(
        "--db-path", default=str(ROOT / "macro_pit_v2.duckdb")
    )
    args = parser.parse_args()
    config = load_config(args.config)
    settings = config.get("semantic_audit")
    if not settings:
        parser.error("the selected config has no semantic_audit section")
    report_path = (
        Path(args.daily_report) if args.daily_report
        else Path(config["report_dir"]) / "latest.json"
    )
    daily_report = json.loads(report_path.read_text(encoding="utf-8"))
    result = run_semantic_audit(
        db_path=args.db_path,
        daily_report=daily_report,
        settings=settings,
        root=ROOT,
    )
    print(json.dumps({
        "status": result["status"],
        "candidate_count": result.get("candidate_count", 0),
        "candidate_total": result.get("candidate_total", 0),
        "api_called": result.get("api_called", False),
        "report_md": result.get("report_md"),
    }, ensure_ascii=False, indent=2))
    return 1 if result["status"] in {"API_ERROR", "REVIEW_REQUIRED"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
