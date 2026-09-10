from __future__ import annotations

from datetime import datetime, timezone

from macro_pit.archive import RawArchive, UrlCache
from macro_pit.db import get_connection
from macro_pit.pipeline import ingest_url_manifest


def test_cached_china_manifest_is_offline_idempotent_and_logged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    url = "http://www.pbc.gov.cn/test-release.html"
    content = (
        "<html><head><title>2025年1月金融统计数据报告</title></head><body>"
        "文章来源：2025-02-14 16:30:05 广义货币（M2）余额同比增长7.0%。"
        "</body></html>"
    ).encode("utf-8")
    archive = RawArchive("data/raw")
    artifact = archive.store(
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
    conn = get_connection(":memory:")
    first = ingest_url_manifest(
        conn,
        source_name="PBOC",
        urls=[url],
        allow_network=False,
        refresh=False,
    )
    second = ingest_url_manifest(
        conn,
        source_name="PBOC",
        urls=[url],
        allow_network=False,
        refresh=False,
    )
    assert first.status == "SUCCESS"
    assert first.new_observations == 1
    assert second.unchanged == 1
    assert conn.execute("select count(*) from observation_vintage").fetchone()[0] == 1
    logs = list((tmp_path / "logs").glob("update_*.json"))
    assert len(logs) == 1
    assert '"status": "SUCCESS"' in logs[0].read_text(encoding="utf-8")
