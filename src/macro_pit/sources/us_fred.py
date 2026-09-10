"""FRED current-history loader intentionally disabled as a PIT source.

The prototype labelled current FRED history as PIT_A and used retrieval time as
historical release time. That corrupts a real-time database. Use RTDSM for US
vintages. A future FRED supplement must archive responses and label final-only
history PIT_D.
"""


class FREDScraper:
    def backfill(self) -> None:
        raise RuntimeError("FRED current history cannot be backfilled as PIT_A; use RTDSM")


if __name__ == "__main__":
    FREDScraper().backfill()
