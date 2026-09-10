"""Run the sealed B01 manifest through the existing bounded NBS archiver."""
import argparse
from pathlib import Path
import runpy

OUT = Path('reports/v2/pit_34_backfill/b01')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-network', action='store_true')
    args = parser.parse_args()
    runner = runpy.run_path('scripts/download_nbs_early_batch.py')['run']
    runner.__globals__.update(OUT=OUT, MANIFEST=Path('config/pit34_b01_candidates.json'),
                              STATE=Path('data/history_backfill/pit34_b01_download_state.json'))
    runner(args.allow_network)
