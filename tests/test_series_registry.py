from macro_pit.series_registry import exclude_inactive_series, inactive_series_ids

import polars as pl


RETIRED_CUSTOMS_FIELDS = {
    "CN_EXPORT_USD",
    "CN_EXPORT_USD_YOY",
    "CN_IMPORT_USD",
    "CN_IMPORT_USD_YOY",
    "CN_TRADE_BALANCE_USD",
}


def test_retired_customs_fields_are_inactive():
    assert RETIRED_CUSTOMS_FIELDS <= set(inactive_series_ids())


def test_retired_fields_are_removed_from_user_facing_frames():
    frame = pl.DataFrame(
        {
            "canonical_series_id": ["CN_CPI_YOY", "CN_EXPORT_USD"],
            "value": [1.0, 2.0],
        }
    )
    filtered = exclude_inactive_series(frame)
    assert filtered.to_dicts() == [
        {"canonical_series_id": "CN_CPI_YOY", "value": 1.0}
    ]
