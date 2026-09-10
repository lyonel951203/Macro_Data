from __future__ import annotations

from pathlib import Path

import click
import duckdb
import yaml

from .acceptance import run_acceptance
from .audit import run_audit
from .db import DB_PATH, get_connection
from .discovery import run_discovery
from .errors import MacroPITError
from .index_discovery import fetch_and_discover_indexes, write_candidates
from .history_worker import run_history_queue
from .nbs_search import discover_nbs_legacy, load_search_terms
from .offline import archive_manual_files, ingest_raw_manifest, load_raw_manifest
from .pipeline import (
    ingest_oecd_manifest,
    ingest_rtdsm_manifest,
    ingest_url_manifest,
    load_url_manifest,
)
from .pit import PIT_MODES, get_snapshot
from .snapshot import build_monthly_snapshots, build_monthly_wide_snapshot


@click.group()
@click.option("--db-path", default=DB_PATH, show_default=True, type=click.Path(path_type=Path))
@click.pass_context
def cli(ctx: click.Context, db_path: Path) -> None:
    """Append-only Global Macro PIT database."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db_path


@cli.command()
def discover() -> None:
    """Build an offline source inventory without making web requests."""
    parquet, report = run_discovery()
    click.echo(f"Declared inventory: {parquet}")
    click.echo(f"Evidence report: {report}")
    click.echo("Historical start/end dates remain UNVERIFIED until a bounded network discovery is run.")


@cli.command("discover-index")
@click.option("--source", type=click.Choice(["NBS", "PBOC", "CUSTOMS", "MOF", "SAFE"]), required=True)
@click.option("--url-manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--allow-network", is_flag=True, help="Explicitly permit conservative official index requests.")
@click.pass_context
def discover_index(
    ctx: click.Context,
    source: str,
    url_manifest: Path,
    allow_network: bool,
) -> None:
    """Archive bounded official index pages and extract candidate release URLs."""
    conn = None
    try:
        conn = get_connection(ctx.obj["db_path"])
        candidates, raw_files = fetch_and_discover_indexes(
            conn,
            source=source,
            urls=load_url_manifest(url_manifest),
            allow_network=allow_network,
        )
        if not candidates:
            raise click.ClickException(
                f"no matching release links found in {len(raw_files)} archived index pages"
            )
        parquet, urls = write_candidates(candidates)
    except (MacroPITError, ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        if conn is not None:
            conn.close()
    click.echo(f"Archived index pages: {len(raw_files)}")
    click.echo(f"Candidate releases: {len(candidates)}")
    click.echo(f"Outputs: {parquet}, {urls}")


@cli.command("discover-nbs-legacy")
@click.option(
    "--term-manifest",
    default="config/nbs_legacy_search_terms.txt",
    show_default=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--start-date", default="2005-01-01", show_default=True)
@click.option("--end-date", default="2020-02-29", show_default=True)
@click.option(
    "--state-path",
    default="data/history_backfill/nbs_legacy_search_state.json",
    show_default=True,
    type=click.Path(path_type=Path),
)
@click.option(
    "--output-dir",
    default="data/discovery/nbs_legacy",
    show_default=True,
    type=click.Path(path_type=Path),
)
@click.option("--max-network-pages", type=click.IntRange(1, 50), default=20, show_default=True)
@click.option("--allow-network", is_flag=True, required=True, help="Required explicit network opt-in.")
@click.pass_context
def discover_nbs_legacy_command(
    ctx: click.Context,
    term_manifest: Path,
    start_date: str,
    end_date: str,
    state_path: Path,
    output_dir: Path,
    max_network_pages: int,
    allow_network: bool,
) -> None:
    """Checkpoint a bounded official-search discovery of pre-2020 NBS releases."""
    try:
        state = discover_nbs_legacy(
            ctx.obj["db_path"],
            terms=load_search_terms(term_manifest),
            start_date=start_date,
            end_date=end_date,
            state_path=state_path,
            output_dir=output_dir,
            allow_network=allow_network,
            max_network_pages=max_network_pages,
        )
    except (MacroPITError, ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"NBS legacy search {state['status']}: network_pages={state.get('network_pages', 0)}, "
        f"candidate_rows={state.get('candidate_rows', 0)}, state={state_path}, output={output_dir}"
    )
    narrowing = [term for term, item in state.get("items", {}).items() if item.get("needs_narrowing")]
    if narrowing:
        click.echo(f"Incomplete search coverage; use narrower date windows: {', '.join(narrowing)}")
    if state["status"] in {"BLOCKED", "PARTIAL"}:
        ctx.exit(1)


@cli.command()
@click.option("--scope", type=click.Choice(["cn", "us", "global"]), required=True)
@click.option("--source", type=click.Choice(["NBS", "PBOC", "CUSTOMS", "MOF", "SAFE", "RTDSM", "OECD"]), required=False)
@click.option("--url-manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=False)
@click.option("--job-manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=False)
@click.option("--allow-network", is_flag=True, help="Explicitly permit conservative official-site requests.")
@click.pass_context
def backfill(
    ctx: click.Context,
    scope: str,
    source: str | None,
    url_manifest: Path | None,
    job_manifest: Path | None,
    allow_network: bool,
) -> None:
    """Backfill a bounded URL manifest; never auto-crawl an unbounded site."""
    if scope == "cn" and (source not in {"NBS", "PBOC", "CUSTOMS", "MOF", "SAFE"} or not url_manifest):
        raise click.UsageError("China backfill requires a China --source and --url-manifest")
    if scope == "us" and (source != "RTDSM" or not job_manifest):
        raise click.UsageError("US backfill requires --source RTDSM and --job-manifest")
    if scope == "global" and (source != "OECD" or not job_manifest):
        raise click.UsageError("Global backfill requires --source OECD and --job-manifest")
    conn = None
    try:
        conn = get_connection(ctx.obj["db_path"])
        if scope == "cn":
            result = ingest_url_manifest(
                conn, source_name=source, urls=load_url_manifest(url_manifest),
                allow_network=allow_network, refresh=False,
            )
        elif scope == "us":
            result = ingest_rtdsm_manifest(
                conn, manifest_path=job_manifest, allow_network=allow_network, refresh=False,
            )
        else:
            result = ingest_oecd_manifest(
                conn, manifest_path=job_manifest, allow_network=allow_network, refresh=False,
            )
    except MacroPITError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        if conn is not None:
            conn.close()
    click.echo(_pipeline_summary(result))
    if result.status != "SUCCESS":
        ctx.exit(1)


@cli.command("backfill-raw")
@click.option("--source", type=click.Choice(["NBS", "PBOC", "CUSTOMS", "MOF", "SAFE"]), required=True)
@click.option("--raw-manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.pass_context
def backfill_raw(ctx: click.Context, source: str, raw_manifest: Path) -> None:
    """Parse verified SHA-named raw files without making network requests."""
    conn = None
    try:
        conn = get_connection(ctx.obj["db_path"])
        result = ingest_raw_manifest(
            conn,
            source_name=source,
            items=load_raw_manifest(raw_manifest),
        )
    except (MacroPITError, ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        if conn is not None:
            conn.close()
    click.echo(
        f"{result.source} offline: files={result.files}, inserted={result.inserted}, "
        f"revisions={result.revisions}, unchanged={result.unchanged}"
    )


@cli.command("archive-manual")
@click.option("--source", type=click.Choice(["NBS", "PBOC", "CUSTOMS", "MOF", "SAFE"]), required=True)
@click.option("--input-dir", type=click.Path(exists=True, file_okay=False, path_type=Path), required=True)
@click.option("--manifest-output", type=click.Path(path_type=Path), required=True)
@click.option("--raw-root", default="data/raw", show_default=True, type=click.Path(path_type=Path))
def archive_manual(
    source: str,
    input_dir: Path,
    manifest_output: Path,
    raw_root: Path,
) -> None:
    """Archive browser-saved official files and emit a reviewed raw manifest."""
    supported = {".html", ".htm", ".json", ".csv", ".xls", ".xlsx"}
    files = sorted(path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in supported)
    if not files:
        raise click.ClickException(f"no supported files found in {input_dir}")
    try:
        items = archive_manual_files(source_name=source, files=files, raw_root=raw_root)
    except (MacroPITError, ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.write_text(
        yaml.safe_dump({"items": items}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    click.echo(f"Archived {len(items)} files; manifest: {manifest_output}")


@cli.command("history-backfill")
@click.option("--source", type=click.Choice(["NBS", "PBOC", "CUSTOMS", "MOF", "SAFE"]), required=True)
@click.option("--candidates", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--start-period", default="2005-01", show_default=True)
@click.option("--state-path", type=click.Path(path_type=Path), required=True)
@click.option("--log-path", type=click.Path(path_type=Path), required=True)
@click.option("--max-network-urls", type=click.IntRange(1, 300), default=20, show_default=True)
@click.option("--wait-across-days", is_flag=True, help="Wait locally and resume the one-time queue next day.")
@click.option("--resume-hour", type=click.IntRange(0, 23), default=10, show_default=True)
@click.option("--allow-network", is_flag=True, required=True, help="Required explicit network opt-in.")
@click.pass_context
def history_backfill(
    ctx: click.Context,
    source: str,
    candidates: Path,
    start_period: str,
    state_path: Path,
    log_path: Path,
    max_network_urls: int,
    wait_across_days: bool,
    resume_hour: int,
    allow_network: bool,
) -> None:
    """Run one persistent, bounded China history queue with checkpoints."""
    state = run_history_queue(
        db_path=ctx.obj["db_path"],
        source_name=source,
        candidate_path=candidates,
        start_period=start_period,
        state_path=state_path,
        log_path=log_path,
        allow_network=allow_network,
        max_network_urls_per_session=max_network_urls,
        wait_across_days=wait_across_days,
        resume_hour=resume_hour,
    )
    click.echo(
        f"{source} history {state['status']}: queue={state.get('queue_size', 0)}, "
        f"pending={state.get('pending', 0)}, state={state_path}, log={log_path}"
    )
    if state["status"] == "BLOCKED":
        ctx.exit(1)


@cli.command()
@click.option("--source", type=click.Choice(["NBS", "PBOC", "CUSTOMS", "MOF", "SAFE", "RTDSM", "OECD"]), required=True)
@click.option("--url-manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=False)
@click.option("--job-manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=False)
@click.option("--allow-network", is_flag=True, required=True, help="Required explicit network opt-in.")
@click.pass_context
def update(
    ctx: click.Context,
    source: str,
    url_manifest: Path | None,
    job_manifest: Path | None,
    allow_network: bool,
) -> None:
    """Run a conditional, rate-limited update for a bounded URL manifest."""
    if source in {"NBS", "PBOC", "CUSTOMS", "MOF", "SAFE"} and not url_manifest:
        raise click.UsageError("China update requires --url-manifest")
    if source in {"RTDSM", "OECD"} and not job_manifest:
        raise click.UsageError(f"{source} update requires --job-manifest")
    conn = None
    try:
        conn = get_connection(ctx.obj["db_path"])
        if source in {"NBS", "PBOC", "CUSTOMS", "MOF", "SAFE"}:
            result = ingest_url_manifest(
                conn, source_name=source, urls=load_url_manifest(url_manifest),
                allow_network=allow_network, refresh=True,
            )
        elif source == "RTDSM":
            result = ingest_rtdsm_manifest(
                conn, manifest_path=job_manifest, allow_network=allow_network, refresh=True,
            )
        else:
            result = ingest_oecd_manifest(
                conn, manifest_path=job_manifest, allow_network=allow_network, refresh=True,
            )
    except MacroPITError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        if conn is not None:
            conn.close()
    click.echo(_pipeline_summary(result))
    if result.status != "SUCCESS":
        ctx.exit(1)


@cli.command()
@click.pass_context
def audit(ctx: click.Context) -> None:
    """Generate reports/audit.html and reports/cn_coverage.csv."""
    conn = _read_connection(ctx.obj["db_path"])
    try:
        result = run_audit(conn)
    finally:
        conn.close()
    for check in result.checks:
        click.echo(f"{check.status:4} {check.name}: {check.value}")
    click.echo(
        "Reports: reports/audit.html, reports/cn_coverage.csv, "
        "reports/us_coverage.csv, reports/global_coverage.csv"
    )
    if not result.passed:
        ctx.exit(1)


@cli.command()
@click.option("--as-of", required=True, help="Timestamp, preferably with UTC offset")
@click.option("--country", default=None)
@click.option("--pit-mode", type=click.Choice(list(PIT_MODES)), default="strict", show_default=True)
@click.pass_context
def snapshot(ctx: click.Context, as_of: str, country: str | None, pit_mode: str) -> None:
    """Print the PIT snapshot visible at a timestamp."""
    conn = _read_connection(ctx.obj["db_path"])
    try:
        frame = get_snapshot(conn, as_of=as_of, country=country, pit_mode=pit_mode)
    finally:
        conn.close()
    click.echo(frame)


@cli.command("export-monthly")
@click.option("--start-date", default="2020-01-31", show_default=True)
@click.option("--end-date", default=None)
@click.option("--country", default=None)
@click.option("--pit-mode", type=click.Choice(list(PIT_MODES)), default="strict", show_default=True)
@click.option("--output-dir", default="data/snapshots", show_default=True, type=click.Path(path_type=Path))
@click.pass_context
def export_monthly(
    ctx: click.Context,
    start_date: str,
    end_date: str | None,
    country: str | None,
    pit_mode: str,
    output_dir: Path,
) -> None:
    """Build month-end parquet snapshots from the vintage database."""
    conn = _read_connection(ctx.obj["db_path"])
    try:
        paths = build_monthly_snapshots(
            conn,
            output_dir,
            start_date,
            end_date,
            country=country,
            pit_mode=pit_mode,
        )
    finally:
        conn.close()
    click.echo(f"Generated {len(paths)} snapshots in {output_dir}")


@cli.command("export-wide")
@click.option("--start-date", default="2005-01-31", show_default=True)
@click.option("--end-date", required=True)
@click.option("--country", default="CN", show_default=True)
@click.option("--pit-mode", type=click.Choice(list(PIT_MODES)), default="strict", show_default=True)
@click.option(
    "--output-prefix",
    default="data/exports/cn_pit_month_end",
    show_default=True,
    type=click.Path(path_type=Path),
)
@click.pass_context
def export_wide(
    ctx: click.Context,
    start_date: str,
    end_date: str,
    country: str,
    pit_mode: str,
    output_prefix: Path,
) -> None:
    """Export a month-end PIT wide values panel plus period and metadata companions."""
    conn = _read_connection(ctx.obj["db_path"])
    try:
        paths = build_monthly_wide_snapshot(
            conn,
            output_prefix,
            start_date,
            end_date,
            country=country,
            pit_mode=pit_mode,
        )
    finally:
        conn.close()
    for label, path in paths.items():
        click.echo(f"{label}: {path}")


@cli.command()
@click.pass_context
def acceptance(ctx: click.Context) -> None:
    """Run the final Definition-of-Done acceptance gate."""
    conn = _read_connection(ctx.obj["db_path"])
    try:
        result = run_acceptance(conn)
    finally:
        conn.close()
    click.echo(result.render())
    if not result.passed:
        ctx.exit(1)


def _read_connection(path: Path) -> duckdb.DuckDBPyConnection:
    if not path.is_file():
        raise click.ClickException(f"database does not exist: {path}")
    return duckdb.connect(str(path), read_only=True)


def _pipeline_summary(result) -> str:
    return (
        f"{result.source} {result.status}: HTTP={result.http_success}, raw={result.raw_downloaded}, "
        f"new={result.new_observations}, revisions={result.revisions}, "
        f"unchanged={result.unchanged}, parse_errors={result.parse_errors}"
    )


if __name__ == "__main__":
    cli()
