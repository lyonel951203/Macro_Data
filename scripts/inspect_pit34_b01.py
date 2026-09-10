"""Print archived B01 paragraphs, relevant table rows, and parser candidates."""
from pathlib import Path
from datetime import datetime
import json
from bs4 import BeautifulSoup
from macro_pit.archive import RawArtifact
from macro_pit.sources.cn_nbs import NBSSource

state = json.loads(Path('data/history_backfill/pit34_b01_download_state.json').read_text(encoding='utf-8'))
source = NBSSource(allow_network=False)
try:
    for item in state['items'].values():
        a = item['artifact'].copy()
        a['retrieved_at'] = datetime.fromisoformat(a['retrieved_at'])
        artifact = RawArtifact(**a)
        content = Path(artifact.path).read_bytes()
        soup = BeautifulSoup(content.decode('utf-8'), 'lxml')
        body = soup.select_one('.txt-content')
        print(item['title'], artifact.path)
        for p in body.find_all('p'):
            text = p.get_text('', strip=True)
            if len(text)>40 and any(w in text for w in ['服务业生产指数','调查失业率','指数为','采购经理指数（PMI）']):
                print(text)
        for tr in body.find_all('tr'):
            cells = [c.get_text('', strip=True) for c in tr.find_all(['td','th'])]
            if cells and any(w in cells[0] for w in ['服务业生产','失业率','2018年1月','指标']):
                print('TABLE', cells)
        try:
            rows = source.parse(content, artifact)
            print('PARSED', [(r['canonical_series_id'],r['period'],r['value'],str(r['available_at'])) for r in rows])
        except Exception as exc:
            print(type(exc).__name__, str(exc))
finally:
    source.close()
