from __future__ import annotations

from click.testing import CliRunner

from macro_pit.cli import cli
from macro_pit.db import get_connection


def test_cli_exposes_required_commands():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for command in ("discover", "discover-index", "backfill", "backfill-raw", "archive-manual", "history-backfill", "update", "audit", "snapshot", "export-monthly", "export-wide", "acceptance"):
        assert command in result.output


def test_discover_is_offline_and_honest(tmp_path, monkeypatch):
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli, ["discover"])
    assert result.exit_code == 0
    assert "UNVERIFIED" in result.output


def test_backfill_scope_without_required_manifest_fails_instead_of_false_success():
    result = CliRunner().invoke(cli, ["backfill", "--scope", "us"])
    assert result.exit_code != 0
    assert "requires --source RTDSM and --job-manifest" in result.output


def test_acceptance_command_returns_nonzero_for_empty_database(tmp_path):
    db_path = tmp_path / "empty.duckdb"
    get_connection(db_path).close()
    result = CliRunner().invoke(cli, ["--db-path", str(db_path), "acceptance"])
    assert result.exit_code == 1
    assert "OVERALL: FAIL" in result.output


def test_archive_manual_command_writes_reusable_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "release.html").write_text(
        '<html><head><meta name="Url" content="/diaochatongjisi/example/index.html"></head></html>',
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli,
        [
            "archive-manual",
            "--source", "PBOC",
            "--input-dir", str(inbox),
            "--manifest-output", "manual.yml",
        ],
    )
    assert result.exit_code == 0
    assert "Archived 1 files" in result.output
    assert (tmp_path / "manual.yml").is_file()
    assert len(list((tmp_path / "data" / "raw" / "pboc").rglob("*.html"))) == 1
