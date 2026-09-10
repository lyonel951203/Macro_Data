from dataclasses import replace
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from macro_pit.archive import RawArtifact
from macro_pit.errors import CrawlSafetyError
from macro_pit.nbs_price_review import review_price_article, search_expectation
from macro_pit.timeutils import SHANGHAI, ensure_aware


@pytest.fixture
def evidence(tmp_path):
    url = "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1900631.html"
    title = "2020年1月份居民消费价格同比上涨5.4%"
    stamp = datetime(2020, 2, 10, 9, 30, tzinfo=SHANGHAI)
    index = tmp_path / "search.json"
    index.write_text(json.dumps({"resultDocs": [{"data": {
        "url": url, "titleO": title, "docDate": "2020-02-10", "dreDate": int(stamp.timestamp() * 1000)
    }}]}, ensure_ascii=False), encoding="utf-8")
    item = {"url": url, "title": title, "period": "2020-01", "indicator": "CN_CPI_YOY",
            "index_raw_file": str(index), "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest()}
    content = f"""<html><head><title>{title} - 国家统计局</title></head><body>
    <div class="detail-title-des"><p>2020/02/10 09:30</p></div>
    <div class="txt-content">2020 年 1 月份，全国居民消费价格同比上涨 5.4%。环比上涨1.4%。</div>
    </body></html>""".encode("utf-8")
    raw = tmp_path / "article.html"
    raw.write_bytes(content)
    artifact = RawArtifact("NBS", url, str(raw), hashlib.sha256(content).hexdigest(), "text/html", stamp, len(content))
    return item, content, artifact


def test_independent_price_review_retains_original_date_despite_migrated_url(evidence):
    item, content, artifact = evidence
    review = review_price_article(item, content, artifact)
    assert review["value"] == 5.4
    assert review["period"] == "2020-01"
    assert review["release_at"] == "2020-02-10T09:30:00+08:00"
    assert review["pit_grade"] == "A"


@pytest.mark.parametrize("old,new", [
    ("上涨 5.4%", "上涨 1.4%"),
    ("上涨 5.4%", "下降 5.4%"),
    ("2020 年 1 月份", "2020 年 2 月份"),
    ("2020/02/10 09:30", "2023/02/03 09:30"),
    ("2020/02/10 09:30", "2020/02/10 10:00"),
    ("2020 年 1 月份", "2020年1—2月份"),
])
def test_independent_price_review_rejects_wrong_value_period_or_release(evidence, old, new):
    item, content, artifact = evidence
    changed = content.decode().replace(old, new).encode()
    assert changed != content
    artifact = replace(artifact, sha256=hashlib.sha256(changed).hexdigest(), size=len(changed))
    with pytest.raises(ValueError):
        review_price_article(item, changed, artifact)


def test_search_evidence_cannot_be_silently_replaced(evidence):
    item, _, _ = evidence
    Path(item["index_raw_file"]).write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        search_expectation(item)


def load_runner():
    path = Path(__file__).resolve().parents[1] / "scripts/run_nbs_price_batch_once.py"
    spec = importlib.util.spec_from_file_location("price_batch_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("blocked", [False, True])
def test_bounded_runner_stops_on_block_and_cleans_lock(tmp_path, monkeypatch, evidence, blocked):
    runner = load_runner()
    item, content, artifact = evidence
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"items": [item]}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    review = review_price_article(item, content, artifact)

    class Source:
        policy = {}
        client = SimpleNamespace(events=[])

        def __init__(self, **kwargs):
            pass

        def fetch(self, *args, **kwargs):
            if blocked:
                raise CrawlSafetyError("HTTP 429; stop")
            return SimpleNamespace(artifact=artifact, content=content, from_cache=True)

        def parse(self, *args):
            return [{**review, "release_at": ensure_aware(review["release_at"]),
                     "available_at": ensure_aware(review["available_at"])}]

        def close(self):
            pass

    calls = []
    monkeypatch.setattr(runner, "NBSSource", Source)
    monkeypatch.setattr(runner, "_validate_manifest", lambda *args: None)
    monkeypatch.setattr(runner.subprocess, "run", lambda args, **kwargs: calls.append(args))
    result = runner.run_batch(manifest, "nbs_test", review_only=True)
    assert result["status"] == ("BLOCKED" if blocked else "COMPLETE")
    assert not Path("data/history_backfill/nbs_price_batch.lock").exists()
    assert len(calls) == (0 if blocked else 1)
    assert all("--ingest" not in call and "--allow-network" not in call for call in calls)
    saved = json.loads(Path("data/history_backfill/nbs_test_run.json").read_text())
    assert saved["status"] == result["status"]


def test_oversized_manifest_rejected_before_fetch(tmp_path):
    runner = load_runner()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"items": [{"url": f"https://example.invalid/{i}"} for i in range(26)]}))
    with pytest.raises(ValueError, match="1..25"):
        runner.run_batch(path, "nbs_test")


def test_resume_after_ingestion_only_rebuilds_exports(tmp_path, monkeypatch, evidence):
    runner = load_runner()
    item, content, artifact = evidence
    review = review_price_article(item, content, artifact)
    monkeypatch.chdir(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"items": [item]}))
    out = Path("reports/v2/nbs_test")
    out.mkdir(parents=True)
    ingestion = {"inserted": 1, "revisions": 0, "unchanged": 0}
    (out / "ingestion_result.json").write_text(json.dumps({"ingestion": ingestion}))
    artifact_dict = {**artifact.__dict__, "retrieved_at": artifact.retrieved_at.isoformat()}
    state_path = Path("data/history_backfill/nbs_test_validation_state.json")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"items": {item["url"]: {"artifact": artifact_dict}},
                                     "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}))
    Path("data/history_backfill/nbs_test_run.json").write_text(json.dumps(
        {"status": "FAILED", "review_only": False, "ingestion": ingestion}))
    inspection = Path("reports/v2/pit_csv_inspection")
    inspection.mkdir()
    (inspection / "field_history_summary.json").write_text("{}")

    class Source:
        policy = {}
        client = SimpleNamespace(events=[])

        def __init__(self, **kwargs):
            pass

        def fetch(self, *args, **kwargs):
            pytest.fail("Resume must use checkpointed raw content")

        def parse(self, *args):
            return [{**review, "release_at": ensure_aware(review["release_at"]),
                     "available_at": ensure_aware(review["available_at"])}]

        def close(self):
            pass

    calls = []

    def command(args, **kwargs):
        calls.append(args)
        if "scripts/finalize_nbs_legacy_batch.py" in args:
            (out / "final_result.json").write_text("{}")

    monkeypatch.setattr(runner, "NBSSource", Source)
    monkeypatch.setattr(runner, "_validate_manifest", lambda *args: None)
    monkeypatch.setattr(runner.subprocess, "run", command)
    notebooks = []
    monkeypatch.setattr(runner, "execute_notebook", notebooks.append)
    result = runner.run_batch(manifest, "nbs_test")
    assert result["status"] == "COMPLETE"
    assert result["ingestion"] == ingestion
    assert len(calls) == 4 and len(notebooks) == 3
    assert all("--ingest" not in call for call in calls)


def test_status_refresh_preserves_surrounding_user_text(tmp_path):
    runner = load_runner()
    path = tmp_path / "STATUS.md"
    path.write_text("user before\n<!-- job:start -->\nold\n<!-- job:end -->\nuser after", encoding="utf-8")
    runner.refresh_status(path, "job", {"status": "BLOCKED", "pid": 1, "updated_at": "now",
                                       "queue_size": 25, "reviewed": 3, "result_path": "result.json",
                                       "error": "HTTP 429"})
    changed = path.read_text(encoding="utf-8")
    assert changed.startswith("user before\n") and changed.endswith("\nuser after")
    assert "BLOCKED" in changed and "HTTP 429" in changed
