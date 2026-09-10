"""Legacy entry point retained only to fail safely.

The original module attempted an unbounded multi-hour government-site crawl.
Use the bounded CLI manifest workflow documented in README.md instead.
"""


def run_all_historical() -> None:
    raise RuntimeError(
        "unbounded historical crawling is disabled; use `python -m macro_pit backfill "
        "--scope cn --source SOURCE --url-manifest FILE --allow-network`"
    )


if __name__ == "__main__":
    run_all_historical()
