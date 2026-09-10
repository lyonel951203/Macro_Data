"""Print compact source evidence for downloaded batch articles; no database I/O."""
import json
import argparse
from pathlib import Path
import re
from lxml import html


def compact(s): return re.sub(r"\s+","",s)


def inspect(since=""):
    out=Path("reports/v2/nbs_economy_batch2")
    state=json.loads(Path("data/history_backfill/nbs_economy_batch2_download_state.json").read_text(encoding="utf-8"))
    for item in state["items"].values():
        if item["period"] < since: continue
        tree=html.fromstring(Path(item["artifact"]["path"]).read_bytes(),parser=html.HTMLParser(encoding="utf-8"))
        body=tree.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," txt-content ")]')[0]
        text=compact(body.text_content())
        tables=body.xpath('.//table')
        monthly=int(item["period"][-2:])
        found=[]
        for table in tables:
            rows=[[compact(c.text_content()) for c in tr.xpath('./td|./th')] for tr in table.xpath('.//tr')]
            if not any(len(r)==3 and re.fullmatch(fr'{monthly}月份?',r[1]) and re.fullmatch(fr'1[-—–至]{monthly}月份?',r[2]) for r in rows[:8]): continue
            for r in rows:
                if len(r)==5 and re.search('规模以上工业增加值|服务业生产指数|固定资产投资（不含农户）|房地产开发投资|商品房销售面积|商品房销售额|社会消费品零售总额|全国城镇调查失业率|居民消费价格$|工业生产者出厂价格$',r[0]):
                    found.append(r)
        header=tree.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," detail-title-des ")]')[0].text_content()
        stamp=re.search(r'20\d\d/\d\d/\d\d\s+\d\d:\d\d',header).group(0)
        para=[compact(p.text_content()) for p in body.xpath('.//p') if '基础设施投资' in compact(p.text_content()) and '制造业投资' in compact(p.text_content())]
        quotes=[]
        for p in para:
            quotes.extend(re.findall(r'(?:基础设施投资|制造业投资)[^，。；]{0,90}',p))
        result=dict(period=item['period'],timestamp=stamp,table_rows=found,investment_quotes=list(dict.fromkeys(quotes)),
                    unemployment_paragraphs=list(dict.fromkeys(compact(p.text_content()) for p in body.xpath('.//p') if '全国城镇调查失业率' in compact(p.text_content()) and len(compact(p.text_content()))<1000)),
                    investment_paragraphs=para,raw=item['artifact']['path'])
        (out/f"source_{item['period']}.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in result.items() if k not in {'investment_paragraphs','raw'}},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since',default='')
    inspect(parser.parse_args().since)
