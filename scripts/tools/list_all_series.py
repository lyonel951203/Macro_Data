"""List all canonical series ids in the database."""
import io
import duckdb

OUT = r"E:\Macro_Data\reports\v2\wind_batch3_plan\all_series_ids.txt"
conn = duckdb.connect(r"E:\Macro_Data\macro_pit_v2.duckdb", read_only=True)
rows = conn.execute(
    "SELECT DISTINCT canonical_series_id FROM observation_vintage ORDER BY 1").fetchall()
with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(r[0] for r in rows))
print(f"{len(rows)} ids")
