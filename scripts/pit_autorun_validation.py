"""Conservative independent evidence gate for unattended NBS gap filling.

Only explicit monthly PMI tables/composite prose and reviewed monthly/YTD
economy columns qualify. Unknown layouts and definitions are held for review.
"""
from datetime import datetime
import hashlib
import re
from lxml import html
from macro_pit.timeutils import SHANGHAI


def compact(value):
    return re.sub(r'\s+', '', value).replace('％','%')


def evidence_values(content, title):
    doc=html.fromstring(content.decode('utf-8'))
    bodies=doc.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," txt-content ")]')
    if not bodies:
        return {}, None
    body=bodies[0]
    text=compact(''.join(body.itertext()))
    full=compact(''.join(doc.itertext()))
    stamps=re.findall(r'(20\d{2})/(\d{2})/(\d{2})(\d{2}):(\d{2})',full)
    if not stamps:
        return {},None
    release=datetime(*map(int,stamps[0]),tzinfo=SHANGHAI)
    expected={}
    tables=[[[compact(''.join(c.itertext())) for c in tr.xpath('./td|./th')]
             for tr in t.xpath('.//tr')] for t in body.xpath('.//table')]

    def put(canonical,period,value,proof):
        key=canonical,period
        if key in expected and expected[key]['value']!=value:
            raise ValueError('Conflicting independent table/prose evidence')
        expected[key]=dict(value=value,proof=proof)

    pmi=re.search(r'(20\d{2})年(\d{1,2})月.*采购经理指数运行情况',compact(title))
    if pmi:
        year,month=map(int,pmi.groups())
        if not 2005<=year<=2026 or not 1<=month<=12:
            return {},release
        label=f'{year}年{month}月'
        period=f'{year:04d}-{month:02d}'
        ids=['CN_PMI_MANUFACTURING','CN_PMI_PRODUCTION','CN_PMI_NEW_ORDERS',
             'CN_PMI_RAW_MATERIAL_INVENTORY','CN_PMI_EMPLOYMENT','CN_PMI_SUPPLIER_DELIVERY']
        for table in tables:
            headers=table[:4]
            manufacturing=any(r==['生产','新订单','原材料库存','从业人员','供应商配送时间'] for r in headers)
            manufacturing=manufacturing or any(r==['','PMI','生产','新订单','原材料库存','从业人员','供应商配送时间'] for r in headers)
            nonman=any(r==['','商务活动','新订单','投入品价格','销售价格','从业人员','业务活动预期'] for r in headers)
            for cells in table:
                if len(cells)!=7 or cells[0]!=label:
                    continue
                if manufacturing:
                    for canonical,cell in zip(ids,cells[1:]):
                        put(canonical,period,float(cell),str(cells))
                if nonman and year>=2007:
                    put('CN_PMI_NONMANUFACTURING',period,float(cells[1]),str(cells))
        composite=re.search(fr'{year}年{month}月份[，,]中国综合PMI产出指数为(\d+(?:\.\d+)?)%',text)
        if composite and year>=2018:
            put('CN_PMI_COMPOSITE',period,float(composite[1]),composite[0])

    caption=re.search(r'(20\d{2})年(\d{1,2})月份(?:及[^。]{0,30})?主要统计数据',text)
    if caption and any(t in title for t in ['国民经济','经济运行']) and '答记者问' not in title:
        year,month=map(int,caption.groups())
        period=f'{year:04d}-{month:02d}'
        # Review scope stays narrower than the production parser. Historical
        # aliases and standalone old investment reports require separate review.
        labels={'服务业生产指数':('CN_SERVICE_PRODUCTION_YOY',2,2017),
                '固定资产投资（不含农户）':('CN_FAI_YTD_YOY',4,2011),
                '房地产开发投资':('CN_REAL_ESTATE_INVESTMENT_YTD_YOY',4,2011),
                '新建商品房销售面积':('CN_NEW_HOME_SALES_AREA_YTD_YOY',4,2024),
                '新建商品房销售额':('CN_NEW_HOME_SALES_VALUE_YTD_YOY',4,2024),
                '全国城镇调查失业率':('CN_URBAN_SURVEYED_UNEMPLOYMENT',1,2018)}
        if year in {2022,2023}:
            labels.update({'商品房销售面积':('CN_NEW_HOME_SALES_AREA_YTD_YOY',4,2022),
                           '商品房销售额':('CN_NEW_HOME_SALES_VALUE_YTD_YOY',4,2022)})
        for table in tables:
            headers=[i for i,r in enumerate(table[:8]) if r==['指标',f'{month}月',f'1-{month}月']]
            if not headers: continue
            h=headers[0]
            if table[h+1]!=['绝对量','同比增长（%）','绝对量','同比增长（%）']: continue
            for cells in table[h+2:]:
                if len(cells)!=5: continue
                label=re.sub(r'^[一二三四五六七八九十]+、','',cells[0])
                label=re.sub(r'[（(](亿元|万平方米|%)[）)]$','',label)
                if label not in labels: continue
                canonical,column,start=labels[label]
                if year<start or (canonical=='CN_SERVICE_PRODUCTION_YOY' and year==2017 and month<3): continue
                if re.fullmatch(r'[+-]?\d+(?:\.\d+)?',cells[column]):
                    put(canonical,period,float(cells[column]),str(cells))
    return expected,release


def verify(content, artifact, title, search_date, parsed, target_ids):
    assert hashlib.sha256(content).hexdigest()==artifact.sha256
    expected,release=evidence_values(content,title)
    if release is None or release.date().isoformat()!=search_date[:10]:
        return [],[{'reason':'missing_or_conflicting_publication_evidence'}]
    accepted=[]; held=[]
    for row in parsed:
        if row['canonical_series_id'] not in target_ids: continue
        key=row['canonical_series_id'],row['period']
        proof=expected.get(key)
        valid=(proof is not None and row['value']==proof['value'] and row['pit_grade']=='A'
               and row['available_at']==release and row['release_at']==release and row['frequency']=='M'
               and row['period']<='2026-07' and release<=datetime(2026,7,31,23,59,59,tzinfo=SHANGHAI))
        canonical=key[0]
        unit='index' if canonical.startswith('CN_PMI_') else ('pct' if canonical.endswith('UNEMPLOYMENT') else 'pct_yoy')
        valid=valid and row['unit']==unit and row['seasonal_adjustment']==('SA' if unit=='index' else 'NSA')
        if unit in {'index','pct'}: valid=valid and 0<=row['value']<=100
        if valid:
            accepted.append((row,proof))
        else:
            held.append(dict(indicator=key[0],period=key[1],reason='no_matching_reviewed_independent_contract'))
    return accepted,held
