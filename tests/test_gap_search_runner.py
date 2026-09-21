from pathlib import Path
import json
import runpy
import subprocess
import sys

import pandas as pd
import pytest


@pytest.mark.parametrize("blocked", [False, True])
def test_bounded_runner_checkpoints_refreshes_status_and_stops_on_block(tmp_path, monkeypatch, blocked):
    import macro_pit.http as http
    import macro_pit.nbs_search as search

    script = Path("scripts/history/run_nbs_gap_search_once.py").read_text(encoding="utf-8")
    (tmp_path / "scripts/history").mkdir(parents=True)
    runner = tmp_path / "scripts/history/run_nbs_gap_search_once.py"
    runner.write_text(script, encoding="utf-8")
    (tmp_path / "config").mkdir()
    jobs = [{"name": "first", "term": "one", "start_date": "2010-01-01", "end_date": "2010-12-31", "max_network_pages": 1},
            {"name": "second", "term": "two", "start_date": "2020-01-01", "end_date": "2020-12-31", "max_network_pages": 3}]
    (tmp_path / "config/jobs.json").write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    candidate_dir = tmp_path / "data/discovery/nbs_legacy"
    candidate_dir.mkdir(parents=True)
    pd.DataFrame({"url": ["https://www.stats.gov.cn/reviewed.html"]}).to_parquet(candidate_dir / "nbs_candidates.parquet")
    report_dir = tmp_path / "reports/v2"
    report_dir.mkdir(parents=True)
    (report_dir / "STATUS.md").write_text("Keep before\n<!-- test:start -->\nOld\n<!-- test:end -->\nKeep after", encoding="utf-8")

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    calls = []
    def discover(db_path, **kwargs):
        calls.append(kwargs["max_network_pages"])
        return {"status": "BLOCKED" if blocked else "PAUSED", "network_pages": 1, "candidate_rows": 1,
                "items": {kwargs["terms"][0]: {"last_page": 1, "total_pages": 5, "next_page": 2}}}

    monkeypatch.setattr(http, "PoliteHttpClient", Client)
    monkeypatch.setattr(search, "discover_nbs_legacy", discover)
    monkeypatch.setattr("macro_pit.config.source_policy", lambda source: {})
    refresh_calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: refresh_calls.append(args))
    monkeypatch.setattr(sys, "argv", [str(runner), "--job-manifest", "config/jobs.json", "--max-pages-per-job", "3", "--status-marker", "test"])
    monkeypatch.chdir(tmp_path)
    if blocked:
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(runner), run_name="__main__")
        assert exc.value.code == 1
    else:
        runpy.run_path(str(runner), run_name="__main__")
    result = json.loads((tmp_path / "data/history_backfill/nbs_gap_search_run.json").read_text(encoding="utf-8"))
    assert result["status"] == ("BLOCKED" if blocked else "FINISHED")
    assert result["max_new_search_pages"] == 4
    assert result["merged_candidates"] == 1
    assert calls == ([1] if blocked else [1, 3])
    assert len(refresh_calls) == 1 and refresh_calls[0][-1] == "--coverage-only"
    status = (report_dir / "STATUS.md").read_text(encoding="utf-8")
    assert status.startswith("Keep before") and status.endswith("Keep after")
    assert result["status"] in status and "Old" not in status
