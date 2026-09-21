from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path

import duckdb
import polars as pl

from .asof_wide import SCOPES
from .series_registry import exclude_inactive_series
from .snapshot import DEFAULT_ESTIMATED_AVAILABILITY


LONG_SCOPES = (*SCOPES, "ALL")
_SCOPE_SQL = {
    "CN": "country = 'CN'",
    "US": "country = 'US'",
    "GLB": "country NOT IN ('CN', 'US')",
    "ALL": "TRUE",
}


@dataclass(frozen=True)
class PitLongResult:
    events: pl.DataFrame
    scope: str
    start_date: date
    end_date: date | None


def build_pit_long(
    conn: duckdb.DuckDBPyConnection,
    scope: str,
    *,
    start_date: str = "2005-01-01",
    end_date: str | None = None,
    estimated_availability_path: str | Path = DEFAULT_ESTIMATED_AVAILABILITY,
    estimated_rules_path: str | Path = "config/estimated_availability_rules_v1.csv",
) -> PitLongResult:
    """Build effective PIT value events without choosing an as-of timestamp.

    Each row states when one field-period value became the selected visible
    value. valid_from is inclusive and valid_to is exclusive. A null valid_to
    means the value remains effective through the latest known event.

    PIT_A/PIT_B is authoritative. Ordinary Wind PIT_D is emitted only when
    that field-period has no A/B record at all. SAFE D is also admitted only
    for CN_FX_RESERVE_USD gaps using its calibrated virtual availability date;
    Eastmoney-D and Sina-D remain lower-priority fallbacks. Dated Wind revisions
    are version events and can
    supersede an older base; a later A/B vintage can then supersede the
    revision. Silent official-page changes are also dated events from their
    first observed timestamp. Other PIT_D rows remain
    excluded unless an explicit estimated-availability rule applies.
    """
    scope = scope.upper()
    if scope not in LONG_SCOPES:
        raise ValueError(f"scope must be one of: {', '.join(LONG_SCOPES)}")
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date) if end_date else None
    if end is not None and end < start:
        raise ValueError("end_date must not be before start_date")

    scope_sql = _SCOPE_SQL[scope]
    db_period_filter = f"period_end >= DATE '{start.isoformat()}'"
    sidecar_period_filter = f"e.period_end >= DATE '{start.isoformat()}'"
    if end is not None:
        db_period_filter += f" AND period_end <= DATE '{end.isoformat()}'"
        sidecar_period_filter += f" AND e.period_end <= DATE '{end.isoformat()}'"

    wind_base_union = ""
    wind_revision_sql = _empty_revision_sql()
    estimated_d_union = ""
    fallback_d_union = ""
    cn_web_revision_sql = _empty_revision_sql()
    imf_revision_sql = _empty_revision_sql()
    if scope in {"CN", "ALL"}:
        sidecar = Path(estimated_availability_path)
        if not sidecar.is_file():
            raise ValueError(
                "CN/ALL long export requires the Wind estimated-availability "
                f"sidecar: {sidecar}"
            )
        safe_path = str(sidecar.resolve()).replace("'", "''")
        conn.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW pit_long_estimated_availability AS
            SELECT canonical_series_id, source, period,
                   CAST(period_end AS DATE) AS period_end, value,
                   CAST(estimated_available_at AS TIMESTAMPTZ) AS visible_from
            FROM read_csv_auto('{safe_path}', header=true)
            WHERE (source = 'WIND' AND canonical_series_id <> 'CN_FX_RESERVE_USD')
               OR (source = 'SAFE' AND canonical_series_id = 'CN_FX_RESERVE_USD')
            """
        )
        wind_base_union = f"""
            UNION ALL
            SELECT 'CN' AS country,
                   e.canonical_series_id,
                   COALESCE(w.source_series_id, e.canonical_series_id) AS source_series_id,
                   COALESCE(w.series_name, e.canonical_series_id) AS series_name,
                   e.source,
                   COALESCE(w.frequency, 'M') AS source_frequency,
                   COALESCE(w.unit, '') AS unit,
                   w.seasonal_adjustment,
                   e.period,
                   COALESCE(w.period_start, e.period_end) AS period_start,
                   e.period_end,
                   e.value,
                   e.visible_from,
                   1 AS source_priority,
                   CASE e.source
                       WHEN 'SAFE' THEN 'SAFE_ESTIMATED_D'
                       ELSE 'WIND'
                   END AS selection_origin,
                   'BASE_PRIORITY' AS event_role,
                   'D' AS pit_grade,
                   NULL::TIMESTAMPTZ AS release_at,
                   'estimated_availability_sidecar' AS release_date_source,
                   w.first_seen_at,
                   COALESCE(w.vintage_no, 0) AS vintage_no,
                   COALESCE(w.revision_type, 'initial') AS revision_type,
                   w.revision_delta,
                   w.source_url,
                   w.raw_file,
                   w.raw_sha256,
                   w.retrieved_at,
                   COALESCE(w.parser_version, 'estimated_availability_v1') AS parser_version
            FROM pit_long_estimated_availability e
            LEFT JOIN (
                SELECT *
                FROM observation_vintage
                WHERE country = 'CN' AND pit_grade = 'D'
                  AND (source = 'WIND' OR (
                      source = 'SAFE'
                      AND canonical_series_id = 'CN_FX_RESERVE_USD'
                  ))
                  AND COALESCE(release_date_source, '') NOT LIKE 'wind_revision_snapshot_%'
                QUALIFY row_number() OVER (
                    PARTITION BY canonical_series_id, period, source
                    ORDER BY retrieved_at DESC, vintage_no DESC
                ) = 1
            ) w
              ON w.canonical_series_id = e.canonical_series_id
             AND w.period = e.period
             AND w.source = e.source
            WHERE {sidecar_period_filter}
              AND NOT EXISTS (
                  SELECT 1
                  FROM observation_vintage official
                  WHERE official.country = 'CN'
                    AND official.canonical_series_id = e.canonical_series_id
                    AND official.period = e.period
                    AND official.pit_grade IN ('A', 'B')
              )
        """
        wind_revision_sql = f"""
            SELECT country, canonical_series_id, source_series_id, series_name,
                   source, frequency AS source_frequency, unit,
                   seasonal_adjustment, period, period_start, period_end, value,
                   available_at AS visible_from,
                   1 AS source_priority,
                   'WIND_REVISION' AS selection_origin,
                   'DATED_REVISION' AS event_role,
                   pit_grade, release_at, release_date_source, first_seen_at,
                   vintage_no, revision_type, revision_delta, source_url,
                   raw_file, raw_sha256, retrieved_at, parser_version
            FROM observation_vintage
            WHERE country = 'CN' AND source = 'WIND' AND pit_grade = 'D'
              AND release_date_source LIKE 'wind_revision_snapshot_%'
              AND {db_period_filter}
        """
        fallback_d_union = f"""
            UNION ALL
            SELECT country, canonical_series_id, source_series_id, series_name,
                   source, frequency AS source_frequency, unit,
                   seasonal_adjustment, period, period_start, period_end, value,
                   available_at AS visible_from,
                   CASE source WHEN 'EASTMONEY_MACRO' THEN 0 ELSE -1 END
                       AS source_priority,
                   CASE source
                       WHEN 'EASTMONEY_MACRO' THEN 'EASTMONEY_D'
                       ELSE 'SINA_D'
                   END AS selection_origin,
                   'BASE_PRIORITY' AS event_role,
                   pit_grade, release_at, release_date_source, first_seen_at,
                   vintage_no, revision_type, revision_delta, source_url,
                   raw_file, raw_sha256, retrieved_at, parser_version
            FROM observation_vintage
            WHERE country = 'CN'
              AND source IN ('EASTMONEY_MACRO', 'SINA_MACRO')
              AND pit_grade = 'D'
              AND release_date_source =
                  'third_party_current_history_first_seen_only'
              AND {db_period_filter}
        """
        cn_web_revision_sql = f"""
            SELECT country, canonical_series_id, source_series_id, series_name,
                   source, frequency AS source_frequency, unit,
                   seasonal_adjustment, period, period_start, period_end, value,
                   available_at AS visible_from,
                   1 AS source_priority,
                   'OBSERVED_WEB_REVISION' AS selection_origin,
                   'DATED_REVISION' AS event_role,
                   pit_grade, release_at, release_date_source, first_seen_at,
                   vintage_no, revision_type, revision_delta, source_url,
                   raw_file, raw_sha256, retrieved_at, parser_version
            FROM observation_vintage
            WHERE country = 'CN' AND pit_grade = 'D'
              AND release_date_source =
                  'official_web_revision_first_seen'
              AND {db_period_filter}
        """

    if scope in {"GLB", "ALL"}:
        rules = Path(estimated_rules_path)
        if not rules.is_file():
            raise ValueError(
                "GLB/ALL long export requires estimated-availability rules: "
                f"{rules}"
            )
        safe_rules = str(rules.resolve()).replace("'", "''")
        conn.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW pit_long_estimated_rules AS
            SELECT canonical_series_id,
                   CAST(lag_days AS INTEGER) AS lag_days,
                   CAST(eligible AS BOOLEAN) AS eligible
            FROM read_csv_auto('{safe_rules}', header=true)
            """
        )
        estimated_d_union = f"""
            UNION ALL
            SELECT country, canonical_series_id, source_series_id, series_name,
                   source, frequency AS source_frequency, unit,
                   seasonal_adjustment, period, period_start, period_end, value,
                   estimated_available_at AS visible_from,
                   1 AS source_priority,
                   'ESTIMATED_D' AS selection_origin,
                   'BASE_PRIORITY' AS event_role,
                   pit_grade, release_at, release_date_source, first_seen_at,
                   vintage_no, revision_type, revision_delta, source_url,
                   raw_file, raw_sha256, retrieved_at, parser_version
            FROM (
                SELECT v.*,
                       CAST(
                           CAST(
                               v.period_end + r.lag_days + 1 AS VARCHAR
                           ) || ' 00:00:00+08:00'
                           AS TIMESTAMPTZ
                       ) AS estimated_available_at
                FROM observation_vintage v
                JOIN pit_long_estimated_rules r
                  USING (canonical_series_id)
                WHERE v.country = 'GLB'
                  AND v.source = 'IMF'
                  AND v.pit_grade = 'D'
                  AND r.eligible
                  AND v.release_date_source LIKE
                      'imf_current_history_snapshot_%'
                  AND {db_period_filter}
                QUALIFY row_number() OVER (
                    PARTITION BY v.canonical_series_id, v.period
                    ORDER BY v.vintage_no DESC, v.retrieved_at DESC
                ) = 1
            ) estimated
        """
        imf_revision_sql = f"""
            SELECT country, canonical_series_id, source_series_id, series_name,
                   source, frequency AS source_frequency, unit,
                   seasonal_adjustment, period, period_start, period_end, value,
                   available_at AS visible_from,
                   1 AS source_priority,
                   'OBSERVED_WEB_REVISION' AS selection_origin,
                   'DATED_REVISION' AS event_role,
                   pit_grade, release_at, release_date_source, first_seen_at,
                   vintage_no, revision_type, revision_delta, source_url,
                   raw_file, raw_sha256, retrieved_at, parser_version
            FROM observation_vintage
            WHERE country = 'GLB' AND source = 'IMF'
              AND pit_grade = 'D'
              AND release_date_source =
                  'official_web_revision_first_seen'
              AND {db_period_filter}
        """

    events = conn.execute(
        f"""
        WITH base_candidates AS (
            SELECT country, canonical_series_id, source_series_id, series_name,
                   source, frequency AS source_frequency, unit,
                   seasonal_adjustment, period, period_start, period_end, value,
                   available_at AS visible_from,
                   CASE pit_grade WHEN 'A' THEN 3 ELSE 2 END AS source_priority,
                   'PIT_' || pit_grade AS selection_origin,
                   'BASE_PRIORITY' AS event_role,
                   pit_grade, release_at, release_date_source, first_seen_at,
                   vintage_no, revision_type, revision_delta, source_url,
                   raw_file, raw_sha256, retrieved_at, parser_version
            FROM observation_vintage
            WHERE {scope_sql}
              AND pit_grade IN ('A', 'B')
              AND {db_period_filter}
            {wind_base_union}
            {fallback_d_union}
            {estimated_d_union}
        ),
        base_deduplicated AS (
            SELECT *
            FROM base_candidates
            QUALIFY row_number() OVER (
                PARTITION BY country, canonical_series_id, period,
                             selection_origin, visible_from
                ORDER BY vintage_no DESC, retrieved_at DESC,
                         source DESC, raw_sha256 DESC
            ) = 1
        ),
        base_thresholds AS (
            SELECT *,
                   min(visible_from) FILTER (
                       WHERE selection_origin = 'PIT_A'
                   ) OVER (
                       PARTITION BY country, canonical_series_id, period
                   ) AS first_a_at,
                   min(visible_from) FILTER (
                       WHERE selection_origin = 'PIT_B'
                   ) OVER (
                       PARTITION BY country, canonical_series_id, period
                   ) AS first_b_at,
                   min(visible_from) FILTER (
                       WHERE selection_origin = 'WIND'
                   ) OVER (
                       PARTITION BY country, canonical_series_id, period
                   ) AS first_wind_at,
                   min(visible_from) FILTER (
                       WHERE selection_origin = 'EASTMONEY_D'
                   ) OVER (
                       PARTITION BY country, canonical_series_id, period
                   ) AS first_eastmoney_at,
                   min(visible_from) FILTER (
                       WHERE selection_origin = 'SAFE_ESTIMATED_D'
                   ) OVER (
                       PARTITION BY country, canonical_series_id, period
                   ) AS first_safe_estimated_at
            FROM base_deduplicated
        ),
        effective_base AS (
            SELECT * EXCLUDE (first_a_at, first_b_at, first_wind_at, first_eastmoney_at, first_safe_estimated_at)
            FROM base_thresholds
            WHERE selection_origin = 'PIT_A'
               OR (
                    selection_origin = 'PIT_B'
                    AND (first_a_at IS NULL OR visible_from < first_a_at)
               )
               OR (
                    selection_origin = 'WIND'
                    AND (first_a_at IS NULL OR visible_from < first_a_at)
                    AND (first_b_at IS NULL OR visible_from < first_b_at)
               )
               OR (
                    selection_origin = 'SAFE_ESTIMATED_D'
                    AND (first_a_at IS NULL OR visible_from < first_a_at)
                    AND (first_b_at IS NULL OR visible_from < first_b_at)
               )
               OR (
                    selection_origin = 'EASTMONEY_D'
                    AND (first_a_at IS NULL OR visible_from < first_a_at)
                    AND (first_b_at IS NULL OR visible_from < first_b_at)
                    AND (first_wind_at IS NULL OR visible_from < first_wind_at)
                    AND (first_safe_estimated_at IS NULL OR visible_from < first_safe_estimated_at)
               )
               OR (
                    selection_origin = 'SINA_D'
                    AND (first_a_at IS NULL OR visible_from < first_a_at)
                    AND (first_b_at IS NULL OR visible_from < first_b_at)
                    AND (first_wind_at IS NULL OR visible_from < first_wind_at)
                    AND (first_eastmoney_at IS NULL OR visible_from < first_eastmoney_at)
                    AND (first_safe_estimated_at IS NULL OR visible_from < first_safe_estimated_at)
               )
               OR (
                    selection_origin = 'ESTIMATED_D'
                    AND (first_a_at IS NULL OR visible_from < first_a_at)
                    AND (first_b_at IS NULL OR visible_from < first_b_at)
               )
        ),
        revision_candidates AS (
            SELECT * FROM ({wind_revision_sql})
            UNION ALL
            SELECT * FROM ({cn_web_revision_sql})
            UNION ALL
            SELECT * FROM ({imf_revision_sql})
        ),
        final_candidates AS (
            SELECT * FROM effective_base
            UNION ALL
            SELECT * FROM revision_candidates
        ),
        same_time_resolved AS (
            SELECT *
            FROM final_candidates
            QUALIFY row_number() OVER (
                PARTITION BY country, canonical_series_id, period, visible_from
                ORDER BY source_priority DESC, vintage_no DESC,
                         retrieved_at DESC, source DESC, raw_sha256 DESC
            ) = 1
        ),
        dated AS (
            SELECT *,
                   lead(visible_from) OVER (
                       PARTITION BY country, canonical_series_id, period
                       ORDER BY visible_from, source_priority DESC, vintage_no DESC
                   ) AS valid_to,
                   row_number() OVER (
                       PARTITION BY country, canonical_series_id, period
                       ORDER BY visible_from, source_priority DESC, vintage_no DESC
                   ) AS event_no
            FROM same_time_resolved
        )
        SELECT country, canonical_series_id, source_series_id, series_name,
               source, source_frequency, unit, seasonal_adjustment,
               period, period_start, period_end, value,
               visible_from AS valid_from, valid_to, event_no,
               selection_origin, event_role, source_priority, pit_grade,
               release_at, release_date_source, first_seen_at, vintage_no,
               revision_type, revision_delta, source_url, raw_file,
               raw_sha256, retrieved_at, parser_version
        FROM dated
        ORDER BY country, canonical_series_id, period_end, period, valid_from
        """
    ).pl()
    events = exclude_inactive_series(events)

    return PitLongResult(
        events=events,
        scope=scope,
        start_date=start,
        end_date=end,
    )


def export_pit_long(
    result: PitLongResult,
    output_prefix: str | Path,
) -> dict[str, Path]:
    prefix = Path(output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    paths = {
        "long_csv": prefix.with_name(prefix.name + ".csv"),
        "long_parquet": prefix.with_name(prefix.name + ".parquet"),
        "export_json": prefix.with_name(prefix.name + "_export.json"),
    }
    result.events.write_csv(paths["long_csv"])
    result.events.write_parquet(paths["long_parquet"])
    fields = (
        result.events.select(["country", "canonical_series_id"]).unique().height
        if not result.events.is_empty()
        else 0
    )
    payload = {
        "scope": result.scope,
        "start_date": result.start_date.isoformat(),
        "end_date": result.end_date.isoformat() if result.end_date else None,
        "rows": result.events.height,
        "fields": fields,
        "grain": "one effective value event per country + field + data period",
        "validity": "valid_from inclusive; valid_to exclusive; null valid_to remains effective",
        "selection_priority": ["PIT_A", "PIT_B", "SAFE_ESTIMATED_D", "WIND", "EASTMONEY_D", "SINA_D", "ESTIMATED_D"],
        "wind_base_rule": "ordinary Wind PIT_D is emitted only when no PIT_A/PIT_B exists for the same field-period",
        "safe_fx_reserve_rule": "SAFE PIT_D for CN_FX_RESERVE_USD is emitted only without A/B and uses the calibrated virtual availability date",
        "wind_revision_rule": "dated Wind revisions are version events",
        "official_web_revision_rule": "silent official-page changes become version events at first observation",
        "contains_source_frequencies": True,
        "requires_as_of_parameter": False,
    }
    paths["export_json"].write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return paths


def default_long_output_prefix(scope: str, start_date: str) -> Path:
    start = date.fromisoformat(start_date)
    return (
        Path("data")
        / "exports"
        / f"{scope.lower()}_pit_long_from_{start.isoformat()}"
    )


def _empty_revision_sql() -> str:
    return """
        SELECT country, canonical_series_id, source_series_id, series_name,
               source, frequency AS source_frequency, unit,
               seasonal_adjustment, period, period_start, period_end, value,
               available_at AS visible_from,
               1 AS source_priority,
               'WIND_REVISION' AS selection_origin,
               'DATED_REVISION' AS event_role,
               pit_grade, release_at, release_date_source, first_seen_at,
               vintage_no, revision_type, revision_delta, source_url,
               raw_file, raw_sha256, retrieved_at, parser_version
        FROM observation_vintage
        WHERE FALSE
    """
