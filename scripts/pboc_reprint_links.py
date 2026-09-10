"""Discover official MOF reprints from archived search results, without guessing article URLs."""
import math
import re
from urllib.parse import urlencode,urlparse
from bs4 import BeautifulSoup
from macro_pit.sources.base import decode_content

SEARCH='https://search.mof.gov.cn/was5/web/search'
TERMS=['金融统计','货币供应量','人民币贷款','人民币存款','社会融资规模','金融运行']

def search_item(term,year=None,page=1):
    params=dict(channelid='229010',searchword=term,searchscope='doccontent',perpage='10',page=str(page),orderby='-DOCRELTIME')
    if year:
        params.update(timescope='customdate',sStartTime=f'{year}.01.01',sEndTime=f'{year}.12.31')
    return dict(url=SEARCH+'?'+urlencode(params),title=f'MOF {year or "all"} {term} page {page}',kind='index',
                discovery='mof_search',term=term,year=year,page=page,evidence='MOF archived search form: channel 229010, doccontent, customdate yyyy.MM.dd')

def parse_search(item,content,raw_file,max_pages=100):
    soup=BeautifulSoup(decode_content(content),'lxml')
    text=soup.get_text(' ',strip=True)
    count=re.search(r'找到相关结果约\s*(\d+)\s*条',text)
    if count is None and soup.select_one('.list_search') is not None and not soup.select('.list_search dl') and '很抱歉，没有找到和您的查询相匹配的结果。' in text:
        return [],dict(total_hits=0,total_pages=0,page=int(item.get('page',1)),eligible_articles=0,review_required=False,result_dates=[],empty_result_template=True)
    if count is None or soup.select_one('.list_search') is None:
        raise ValueError('MOF search response missing result count or results container')
    found={};dates=[];eligible=[]
    for entry in soup.select('.list_search dl'):
        link=entry.select_one('dt a[href]')
        if not link:continue
        title=link.get_text(' ',strip=True);url=link['href'];parsed=urlparse(url)
        if parsed.scheme not in {'http','https'} or parsed.hostname!='www.mof.gov.cn' or parsed.query:continue
        if not re.fullmatch(r'/zhengwuxinxi/caijingshidian/[^/]+/\d{6}/t\d{8}_\d+\.htm[l]?',parsed.path):continue
        date=entry.select_one('.fr');stamp=date.get_text(strip=True) if date else ''
        dates.append(stamp)
        if item.get('year') and not stamp.startswith(str(item['year'])+'.'):
            raise ValueError('MOF ignored requested year or result date missing; hold this window')
        # Prefer HTTPS on the same verified MOF host; preserve the original result link.
        canonical=parsed._replace(scheme='https',fragment='').geturl()
        found[canonical]=dict(url=canonical,title=title,kind='article',evidence=raw_file,discovered_from=item['url'],
                              original_result_url=url,index_publication_date=stamp,pit_review='PENDING')
        eligible.append(canonical)
    total=int(count.group(1));page=int(item.get('page',1));pages=max(1,math.ceil(total/10))
    if total and not soup.select('.list_search dl'):raise ValueError('Nonzero result count without result rows')
    pagination=[]
    if page<min(pages,max_pages):
        next_item=search_item(item['term'],item.get('year'),page+1)
        next_item.update(evidence=raw_file,discovered_from=item['url'])
        pagination.append(next_item)
    return sorted(found.values(),key=lambda row:(row['index_publication_date'],row['url']))+pagination,dict(
        total_hits=total,total_pages=pages,page=page,eligible_articles=len(eligible),
        review_required=pages>max_pages,result_dates=dates)
