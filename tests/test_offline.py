from __future__ import annotations

import hashlib

import pytest

from macro_pit.db import get_connection
from macro_pit.errors import DataContractError
from macro_pit.offline import archive_manual_files, ingest_raw_manifest


def pboc_raw(tmp_path):
    content = """<html><head>
    <title>2025年1月金融统计数据报告</title>
    <meta name="Url" content="/diaochatongjisi/example/index.html">
    </head><body>文章来源：2025-02-14 16:30:05
    广义货币（M2）余额同比增长7.0%。</body></html>""".encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    path = tmp_path / f"{digest}.html"
    path.write_bytes(content)
    return path


def test_offline_raw_manifest_infers_official_url_and_is_idempotent(tmp_path):
    path = pboc_raw(tmp_path)
    conn = get_connection(":memory:")
    first = ingest_raw_manifest(conn, source_name="PBOC", items=[{"path": str(path), "url": ""}])
    second = ingest_raw_manifest(conn, source_name="PBOC", items=[{"path": str(path), "url": ""}])
    assert first.inserted == 1
    assert second.unchanged == 1
    url, raw_file = conn.execute("select source_url, raw_file from observation_vintage").fetchone()
    assert url == "http://www.pbc.gov.cn/diaochatongjisi/example/index.html"
    assert raw_file == path.as_posix()


def test_offline_raw_rejects_filename_hash_mismatch(tmp_path):
    path = tmp_path / "wrong.html"
    path.write_text("content", encoding="utf-8")
    conn = get_connection(":memory:")
    with pytest.raises(DataContractError, match="filename/hash mismatch"):
        ingest_raw_manifest(
            conn,
            source_name="PBOC",
            items=[{"path": str(path), "url": "http://www.pbc.gov.cn/example"}],
        )


def test_manual_file_is_copied_to_sha_archive_without_deleting_original(tmp_path):
    inbox = tmp_path / "manual.html"
    inbox.write_text(
        '<html><head><meta name="Url" content="/diaochatongjisi/example/index.html"></head></html>',
        encoding="utf-8",
    )
    items = archive_manual_files(
        source_name="PBOC",
        files=[inbox],
        raw_root=tmp_path / "raw",
    )
    archived = __import__("pathlib").Path(items[0]["path"])
    assert inbox.is_file()
    assert archived.is_file()
    assert len(archived.stem) == 64
