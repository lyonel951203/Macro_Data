import base64
import hashlib
import io
import json
from datetime import datetime
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook
from openpyxl.comments import Comment

from macro_pit.errors import DataContractError
from macro_pit.wind import decode_edb_comment, review_workbook


def fixture_manifest(tmp_path, *, blank_to_zero=True, changes=None, unit="亿美元", duplicate=False, formula=False):
    metric = dict(code="M0000606", name="中国:出口金额:当月值", unit=unit, freq=4,
                  extractTag=True, changeRecord=changes or [])
    settings = dict(exportConfig=dict(blankTo=1 if blank_to_zero else 0, blankValue="0"), metric=[metric])
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as z:
        z.writestr("0", b"EDB\0\r\n\0\0\0" + json.dumps(settings).encode())
    wb = Workbook()
    sheet = wb.active
    sheet.append(["Wind"])
    sheet["A1"].comment = Comment(base64.b64encode(stream.getvalue()).decode(), "Wind")
    for label, value in [("指标名称", metric["name"]), ("频率", "月"), ("单位", unit),
                         ("指标ID", metric["code"]), ("来源", "海关总署")]:
        sheet.append([label, value])
    sheet.append([datetime(2020, 1, 31), "=1+2" if formula else 100])
    sheet.append([datetime(2020, 1, 31) if duplicate else datetime(2020, 2, 29), 0])
    path = tmp_path / "input.xlsx"
    wb.save(path)
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                first_seen_at="2026-09-08T14:10:00+08:00", retrieved_at="2026-09-08T14:10:00+08:00",
                url=path.as_uri())


def test_wind_preserves_source_and_never_backdates(tmp_path):
    result = review_workbook(fixture_manifest(tmp_path))
    row, = result["observations"]
    assert row["value"] == 10 and row["unit"] == "bn_usd"
    assert row["source"] == "WIND" and row["source_series_id"] == "M0000606"
    assert row["pit_grade"] == "D" and row["release_at"] is None
    assert row["available_at"] == row["first_seen_at"]
    assert result["cells"][1]["reasons"] == "ambiguous_zero_after_blank_fill"


def test_wind_keeps_real_zero_when_export_did_not_fill(tmp_path):
    result = review_workbook(fixture_manifest(tmp_path, blank_to_zero=False))
    assert len(result["observations"]) == 2
    assert result["observations"][1]["value"] == 0


def test_wind_quarantines_transforms_even_for_known_code(tmp_path):
    result = review_workbook(fixture_manifest(tmp_path, changes=[dict(command=dict(name="FREQ_UP"))]))
    assert not result["observations"]
    assert "transformed_series" in result["cells"][0]["reasons"]


@pytest.mark.parametrize("kwargs, error", [({"unit": "亿元"}, "metadata changed"),
                                         ({"duplicate": True}, "Duplicate Wind")])
def test_wind_fails_closed_on_mapping_and_key_changes(tmp_path, kwargs, error):
    with pytest.raises(DataContractError, match=error):
        review_workbook(fixture_manifest(tmp_path, **kwargs))


def test_wind_never_executes_cell_formulas(tmp_path):
    result = review_workbook(fixture_manifest(tmp_path, formula=True))
    assert not result["observations"]
    assert "formula_value" in result["cells"][0]["reasons"]


def test_wind_raw_integrity(tmp_path):
    manifest = fixture_manifest(tmp_path)
    manifest["sha256"] = "0" * 64
    with pytest.raises(DataContractError, match="SHA256 mismatch"):
        review_workbook(manifest)


def test_wind_settings_must_be_inspectable():
    with pytest.raises(DataContractError, match="Cannot verify"):
        decode_edb_comment("not base64")
