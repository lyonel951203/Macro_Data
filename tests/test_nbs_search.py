from __future__ import annotations

from macro_pit.nbs_search import candidates_from_search, discover_nbs_legacy
import json
from types import SimpleNamespace
import pytest
from macro_pit.errors import DataContractError, CrawlSafetyError


EMPTY_QUERY = {"ok": False, "code": 201, "msg": "无搜索词", "resultDocs": []}


def retry_setup(tmp_path, monkeypatch, responses):
    import macro_pit.nbs_search as search
    monkeypatch.setattr(search, "_record_events", lambda db, client, offset: len(client.events))

    class Client:
        source = "NBS"
        def __init__(self):
            self.events = []
            self.calls = []
            self._request_count = 0

        def fetch_form(self, endpoint, params, refresh):
            self.calls.append((dict(params), refresh))
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            payload, cached, network = response
            self._request_count += network
            return SimpleNamespace(content=json.dumps(payload).encode(), from_cache=cached,
                                   artifact=SimpleNamespace(path=f"raw_{len(self.calls)}.json"))

    options = dict(db_path=tmp_path / "db.duckdb", terms=["经济运行"],
                   start_date="2014-01-01", end_date="2014-12-31",
                   state_path=tmp_path / "state.json", output_dir=tmp_path / "candidates",
                   allow_network=True, max_network_pages=1, client=Client())
    state = search._load_state(options["state_path"], options["terms"], options["start_date"], options["end_date"])
    state["items"]["经济运行"].update(next_page=9, last_page=8)
    search._save_state(options["state_path"], state)
    return options


def test_cached_empty_query_refreshes_same_page_without_losing_checkpoint(tmp_path, monkeypatch):
    document = {"data": {"titleO": "2014年9月经济运行", "docDate": "2014-10-20",
                         "url": "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1898468.html"}}
    options = retry_setup(tmp_path, monkeypatch, [
        (EMPTY_QUERY, True, 0), (EMPTY_QUERY, True, 1),
        ({"ok": True, "totalHits": 180, "resultDocs": [document]}, False, 1),
    ])
    first = discover_nbs_legacy(**options)
    item = first["items"]["经济运行"]
    assert first["status"] == "PAUSED" and not item["complete"]
    assert item["next_page"] == 9 and item["last_page"] == 8
    assert first["candidate_rows"] == 0
    assert first["network_pages"] == 1 and first["cached_pages"] == 1
    assert not (tmp_path / "candidates" / "nbs_candidates.parquet").exists()
    final = discover_nbs_legacy(**options)
    assert final["status"] == "COMPLETE" and final["candidate_rows"] == 1
    assert final["items"]["经济运行"]["next_page"] == 10
    assert "empty_query_retry" not in final["items"]["经济运行"]
    assert "last_error" not in final
    assert len(final["items"]["经济运行"]["search_errors"]) == 2
    calls = options["client"].calls
    assert [refresh for _, refresh in calls] == [False, True, True]
    assert all(params == calls[0][0] for params, _ in calls)
    discover_nbs_legacy(**options)
    assert len(calls) == 3


def test_repeated_empty_query_is_bounded_across_restarts(tmp_path, monkeypatch):
    options = retry_setup(tmp_path, monkeypatch, [(EMPTY_QUERY, True, 1)] * 3)
    for _ in range(2):
        assert discover_nbs_legacy(**options)["status"] == "PAUSED"
    with pytest.raises(DataContractError, match="retries exhausted"):
        discover_nbs_legacy(**options)
    with pytest.raises(DataContractError, match="retries exhausted"):
        discover_nbs_legacy(**options)
    assert len(options["client"].calls) == 3
    state = json.loads(options["state_path"].read_text(encoding="utf-8"))
    assert state["status"] == "ERROR"
    assert state["items"]["经济运行"]["next_page"] == 9
    assert not state["items"]["经济运行"]["complete"]


def test_other_search_errors_are_not_retried(tmp_path, monkeypatch):
    options = retry_setup(tmp_path, monkeypatch, [({"ok": False, "code": 403, "msg": "denied"}, False, 1)])
    with pytest.raises(DataContractError, match="denied"):
        discover_nbs_legacy(**options)
    assert len(options["client"].calls) == 1


def test_empty_query_retry_still_stops_on_source_block(tmp_path, monkeypatch):
    options = retry_setup(tmp_path, monkeypatch, [(EMPTY_QUERY, True, 0), CrawlSafetyError("HTTP 429")])
    state = discover_nbs_legacy(**options)
    assert state["status"] == "BLOCKED" and "429" in state["last_error"]
    assert state["items"]["经济运行"]["next_page"] == 9


@pytest.mark.parametrize("terms", [[], [""], [" "], ["经济运行", ""]])
def test_empty_input_terms_rejected_before_fetch(tmp_path, monkeypatch, terms):
    options = retry_setup(tmp_path, monkeypatch, [])
    options["terms"] = terms
    with pytest.raises(ValueError, match="nonempty"):
        discover_nbs_legacy(**options)
    assert not options["client"].calls


def test_search_candidates_keep_only_canonical_nbs_release_urls():
    payload = {
        "ok": True,
        "resultDocs": [
            {
                "data": {
                    "titleO": "11月份居民消费价格总水平同比上涨1.3%",
                    "url": "http://www.stats.gov.cn/sj/zxfb/202303/t20230301_1919566.html?x=1",
                    "docDate": "2005-12-12",
                }
            },
            {
                "data": {
                    "titleO": "外部社交平台结果",
                    "url": "https://weibo.com/example",
                    "docDate": "2005-12-12",
                }
            },
            {
                "data": {
                    "titleO": "统计解读而非发布稿",
                    "url": "https://www.stats.gov.cn/sj/sjjd/202302/t20230201_1.html",
                    "docDate": "2005-12-12",
                }
            },
        ],
    }

    candidates = candidates_from_search(payload, raw_file="raw.json", term="居民消费价格")

    assert len(candidates) == 1
    assert candidates[0].url == "https://www.stats.gov.cn/sj/zxfb/202303/t20230301_1919566.html"
    assert candidates[0].period == "2005-11"


def test_search_candidate_rolls_december_period_back_from_january_release():
    payload = {
        "ok": True,
        "resultDocs": [
            {
                "data": {
                    "titleO": "12月份居民消费价格总水平同比上涨",
                    "url": "https://www.stats.gov.cn/sj/zxfb/202303/t20230301_1919000.html",
                    "docDate": "2006-01-12",
                }
            }
        ],
    }

    candidate = candidates_from_search(payload, raw_file="raw.json", term="居民消费价格")[0]

    assert candidate.period == "2005-12"


def test_repeating_search_page_is_not_complete_and_resume_skips_it(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import macro_pit.nbs_search as search

    calls = []
    document = {"data": {"titleO": "2005年1月份居民消费价格同比上涨1.9%",
                         "url": "https://www.stats.gov.cn/sj/zxfb/202303/t20230301_1919000.html",
                         "docDate": "2005-02-20"}}

    class Client:
        def __init__(self, **kwargs):
            self.events = []

        def fetch_form(self, endpoint, params, refresh):
            calls.append((params["qt"], params["page"]))
            payload = {"ok": True, "totalHits": 21, "currentHits": 20,
                       "requestId": len(calls), "resultDocs": [document]}
            return SimpleNamespace(content=json.dumps(payload).encode(), from_cache=False,
                                   artifact=SimpleNamespace(path=f"page_{len(calls)}.json"))

        def close(self):
            pass

    monkeypatch.setattr(search, "PoliteHttpClient", Client)
    monkeypatch.setattr(search, "_record_events", lambda db, client, offset: 0)
    options = dict(db_path=tmp_path / "db.duckdb", terms=["居民消费价格"],
                   start_date="2005-01-01", end_date="2005-12-31",
                   state_path=tmp_path / "state.json", output_dir=tmp_path / "candidates",
                   allow_network=True, max_network_pages=5)
    state = discover_nbs_legacy(**options)
    assert state["status"] == "PARTIAL"
    assert state["candidate_rows"] == 1
    assert state["network_pages"] == 2
    item = state["items"]["居民消费价格"]
    assert not item["complete"]
    assert item["needs_narrowing"]
    assert item["pagination_repeat"]["matches_page"] == 1
    resumed = discover_nbs_legacy(**options)
    assert resumed["status"] == "PARTIAL"
    assert len(calls) == 2  # No automatic retry of an exhausted result window.


def test_date_windows_share_client_without_replaying_crawl_events(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import macro_pit.nbs_search as search

    class Client:
        source = "NBS"
        events = []
        closed = False

        def fetch_form(self, endpoint, params, refresh):
            self.events.append(params["startDateStr"])
            return SimpleNamespace(content=json.dumps({"ok": True, "totalHits": 0, "resultDocs": []}).encode(),
                                   from_cache=False, artifact=SimpleNamespace(path="raw.json"))

        def close(self):
            self.closed = True

    recorded = []
    def record(db_path, client, offset):
        recorded.extend(client.events[offset:])
        return len(client.events)

    client = Client()
    monkeypatch.setattr(search, "_record_events", record)
    for year in [2005, 2010]:
        state = discover_nbs_legacy(
            tmp_path / "db.duckdb", terms=["居民消费价格"], start_date=f"{year}-01-01",
            end_date=f"{year}-12-31", state_path=tmp_path / f"{year}.json",
            output_dir=tmp_path / "candidates", allow_network=True, max_network_pages=1, client=client,
        )
        assert state["status"] == "COMPLETE"
        assert not client.closed
    assert recorded == ["2005-01-01", "2010-01-01"]
