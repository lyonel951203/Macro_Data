from __future__ import annotations

from datetime import datetime, timezone

import polars as pl

from macro_pit.archive import RawArchive, UrlCache
from macro_pit.db import get_connection
from macro_pit.history_worker import run_history_queue


def test_cached_history_queue_is_offline_checkpointed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    url = "http://www.pbc.gov.cn/test-history-release.html"
    content = (
        "<html><head><title>2025年1月金融统计数据报告</title></head><body>"
        "文章来源：2025-02-14 16:30:05 广义货币（M2）余额同比增长7.0%。"
        "</body></html>"
    ).encode("utf-8")
    artifact = RawArchive("data/raw").store(
        source="PBOC",
        url=url,
        content=content,
        content_type="text/html",
        retrieved_at=datetime(2025, 2, 20, tzinfo=timezone.utc),
    )
    UrlCache("data/http_cache").put(
        "PBOC",
        url,
        {
            "url": url,
            "resolved_url": url,
            "raw_file": artifact.path,
            "raw_sha256": artifact.sha256,
            "content_type": artifact.content_type,
            "retrieved_at": artifact.retrieved_at.isoformat(),
            "size": artifact.size,
            "etag": None,
            "last_modified": None,
        },
    )
    candidates = tmp_path / "candidates.parquet"
    pl.DataFrame({"url": [url], "period": ["2025-01"]}).write_parquet(candidates)
    db_path = tmp_path / "history.duckdb"
    get_connection(db_path).close()

    state = run_history_queue(
        db_path=db_path,
        source_name="PBOC",
        candidate_path=candidates,
        start_period="2005-01",
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "worker.jsonl",
        allow_network=False,
        max_network_urls_per_session=1,
        wait_across_days=False,
    )

    assert state["status"] == "COMPLETE"
    assert state["items"][url]["status"] == "success"
    assert state["items"][url]["from_cache"] is True
    conn = get_connection(db_path)
    try:
        assert conn.execute("select count(*) from observation_vintage").fetchone()[0] == 1
        assert conn.execute("select count(*) from crawl_log").fetchone()[0] == 1
    finally:
        conn.close()
