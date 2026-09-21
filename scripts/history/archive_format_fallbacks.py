"""Bounded offline fallback formats; outputs remain unverified candidates."""
import re
from datetime import datetime,timedelta
from urllib.parse import urlparse
from lxml import html
from macro_pit.sources.cn_common import make_observation
from macro_pit.timeutils import SHANGHAI

def compact(s):return re.sub(r'\s+','',s).replace('，',',').replace('％','%').replace('—','-').replace('–','-')
def unique(pattern,text):
 matches=list(re.finditer(pattern,text));assert len(matches)==1,'missing_or_ambiguous_scoped_statement';return matches[0]
def nbs(content,artifact):
 assert urlparse(artifact.url).hostname=='www.stats.gov.cn'
 d=html.fromstring(content.decode('utf-8'));title=compact(d.findtext('.//title') or '')
 bodies=d.xpath('//div[@class="txt-content"]');headers=d.xpath('//div[@class="detail-title-des"]');assert len(bodies)==len(headers)==1
 text=compact(bodies[0].text_content())
 stamp=unique(r'20\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}',headers[0].text_content())[0]
 date=datetime.strptime(' '.join(stamp.split()),'%Y/%m/%d %H:%M').replace(tzinfo=SHANGHAI)
 growth=r'(?P<direction>增长|下降)(?P<value>\d+(?:\.\d+)?)%'
 if '规模以上工业生产' in title:
  tm=unique(r'(20\d{2})年(\d{1,2})月份?',title);y,m=map(int,tm.groups())
  q=unique(fr'{y}年{m}月份?,规模以上工业增加值同比(?:实际)?'+growth,text[:500])
  key='CN_INDUSTRIAL_VALUE_ADDED_YOY';name='规模以上工业增加值同比'
 elif '房地产' in title or '固定资产投资（不含农户）' in title:
  tm=unique(r'(20\d{2})年1-(\d{1,2})月份?',title);y,m=map(int,tm.groups())
  if '房地产' in title:label=r'全国(?:完成)?房地产开发投资';key='CN_REAL_ESTATE_INVESTMENT_YTD_YOY';name='房地产开发投资累计同比'
  else:
   assert y>=2011,'old_investment_scope'
   label=r'全国固定资产投资（不含农户）';key='CN_FAI_YTD_YOY';name='固定资产投资累计同比'
  q=unique(fr'(?:{y}年)?1-{m}月份?,{label}\d+(?:\.\d+)?亿元,(?:同比|比上年同期)(?:名义)?'+growth,text[:500])
 else:raise ValueError('unsupported_nbs_special_release_title')
 assert 1<=m<=12
 import calendar
 period_end=datetime(y,m,calendar.monthrange(y,m)[1],tzinfo=SHANGHAI)
 assert 0<=(date-period_end).days<=45 and date<=artifact.retrieved_at,'publication_period_mismatch'
 value=float(q['value'])*(-1 if q['direction']=='下降' else 1)
 row=make_observation(source='NBS',canonical_series_id=key,source_series_id=key[3:],series_name=name,unit='pct_yoy',year=y,month=m,value=value,artifact=artifact,release=dict(release_at=date,available_at=date,pit_grade='A',release_date_source='official_page_timestamp'),parser_version='nbs_special_release_fallback_v1')
 return [row]
def safe(content,artifact):
 from review_safe_reserves import extract as reserves,verify
 from parse_safe_monthly_review import extract as flows,METRICS
 assert urlparse(artifact.url).hostname=='www.safe.gov.cn'
 try:
  y,m,date,value,quote=reserves(content);verify(content,y,m,date,value)
  values={'CN_FX_RESERVE_USD':value};names={'CN_FX_RESERVE_USD':'外汇储备'};version='safe_reserves_fallback_v1'
 except (AssertionError,ValueError,AttributeError,TypeError):
  y,m,date,values,proof,title=flows(content);names=dict(METRICS);version='safe_monthly_flows_fallback_v1'
 assert date+timedelta(days=1)<=artifact.retrieved_at
 return [make_observation(source='SAFE',canonical_series_id=key,source_series_id=key[3:],series_name=names[key],unit='bn_usd',year=y,month=m,value=float(value),artifact=artifact,release=dict(release_at=date,available_at=date+timedelta(days=1),pit_grade='B',release_date_source='safe_official_metadata_date_next_day'),parser_version=version) for key,value in values.items()]
def pboc(content,artifact):
 from macro_pit.sources.cn_pboc import METRICS
 assert urlparse(artifact.url).hostname=='www.mof.gov.cn','unsupported_reprint_host'
 d=html.fromstring(content.decode('utf-8'));b=d.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," my_conboxzw ")]');assert len(b)==1
 for node in b[0].xpath('.//script|.//style'):node.drop_tree()
 text=compact(b[0].text_content());period=unique(r'(20\d{2})年(\d{1,2})月末',text[:600]);y,m=map(int,period.groups())
 stamps=d.xpath('//meta[@name="PubDate"]/@content');assert len(stamps)==1
 date=datetime.fromisoformat(stamps[0][:10]).replace(tzinfo=SHANGHAI)
 import calendar
 end=datetime(y,m,calendar.monthrange(y,m)[1],tzinfo=SHANGHAI);assert 0<=(date-end).days<=45
 release=dict(release_at=date,available_at=date+timedelta(days=1),pit_grade='B',release_date_source='mof_reprint_date_conservative_original_release_unverified');assert release['available_at']<=artifact.retrieved_at
 patterns={
 'CN_M2_YOY':r'广义货币(?:供应量)?[（(]M2[）)]余额(?:为)?[\d.]+万亿元,同比',
 'CN_M1_YOY':r'狭义货币(?:供应量)?[（(]M1[）)]余额(?:为)?[\d.]+万亿元,同比',
 'CN_M0_YOY':r'(?:市场货币流通量|流通中货币)[（(]M0[）)]余额(?:为)?[\d.]+万亿元,同比',
 'CN_RMB_LOAN_BAL_YOY':r'人民币(?:各项)?贷款余额(?:为)?[\d.]+万亿元,同比',
 'CN_RMB_DEPOSIT_BAL_YOY':r'人民币(?:各项)?存款余额(?:为)?[\d.]+万亿元,同比'}
 rows=[]
 for metric in METRICS:
  if metric.canonical_id not in patterns:continue
  matches=list(re.finditer(patterns[metric.canonical_id]+r'(增长|下降)([\d.]+)%',text))
  if not matches:continue
  assert len(matches)==1,'ambiguous_money_metric'
  q=matches[0];value=float(q[2])*(-1 if q[1]=='下降' else 1)
  rows.append(make_observation(source='PBOC',canonical_series_id=metric.canonical_id,source_series_id=metric.source_id,series_name=metric.name,unit=metric.unit,year=y,month=m,value=value,artifact=artifact,release=release,parser_version='pboc_mof_explicit_month_fallback_v1'))
 assert rows,'no_supported_money_growth'
 return rows

def parse(source,content,artifact):return {'NBS':nbs,'SAFE':safe,'PBOC':pboc}[source](content,artifact)
