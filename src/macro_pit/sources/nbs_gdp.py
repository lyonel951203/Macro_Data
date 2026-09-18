"""Explicit current-quarter GDP table, never historical or cumulative columns."""
import re
from ..errors import DataContractError

def compact(s):return re.sub(r'\s+','',s).replace('（','(').replace('）',')').replace('—','-')
def current_gdp(soup):
 title=compact(soup.title.get_text() if soup.title else '')
 match=re.search(r'(20\d{2})年([一二三四1-4])季度',title)
 if not match:return current_from_cumulative_title(soup)
 y=int(match[1]);q=int(match[2]) if match[2].isdigit() else '一二三四'.index(match[2])+1
 if '初步核算' not in title or not re.search(r'GDP|国内生产总值',title,re.I):raise DataContractError('not_initial_GDP_quarter_release')
 bodies=soup.select('.txt-content')
 if len(bodies)!=1:raise DataContractError('missing_unique_GDP_body')
 found=[]
 for table in bodies[0].find_all('table'):
  rows=[[compact(c.get_text()) for c in tr.find_all(['th','td'],recursive=False)] for tr in table.find_all('tr')]
  for i,row in enumerate(rows):
   if row and len(row)==3 and row[1]=='现价总量(亿元)':row=[row[0],'绝对额(亿元)',row[2]]
   if row not in [['','绝对额(亿元)','比上年同期增长(%)'],['','绝对额(亿元)','比去年同期增长(%)']]:continue
   if q==1 and i+2<len(rows) and rows[i+1] in [['1季度','1季度'],['一季度','一季度']] and len(rows[i+2])==3 and rows[i+2][0] in ['GDP','国内生产总值']:
    found.append(float(rows[i+2][2]))
   elif q==1 and i+1<len(rows) and rows[i+1][0] in ['GDP','国内生产总值']:
    data=rows[i+1]
    if len(data)==3:found.append(float(data[2]))
   elif i+2<len(rows):
    header=rows[i+1];data=rows[i+2]
    single={f'{q}季度',f'{"一二三四"[q-1]}季度'}
    cumulative={f'1-{q}季度','上半年' if q==2 else '全年' if q==4 else f'前三季度'}
    if len(header)==4 and header[0] in single and header[2] in single and header[1] in cumulative and header[3]==header[1] and len(data)==5 and data[0] in ['GDP','国内生产总值']:
     found.append(float(data[3]))
 if not found or len(set(found))!=1:raise DataContractError('unverified_or_conflicting_current_GDP_yoy_header')
 return y,q,found[0]

def current_from_cumulative_title(soup):
 title=compact(soup.title.get_text() if soup.title else '')
 match=re.search(r'(20\d{2})年(?:1-([2-4])季度|(上半年))',title)
 if not match or '初步核算' not in title:raise DataContractError('no_supported_cumulative_GDP_title')
 y=int(match[1]);q=int(match[2]) if match[2] else 2
 bodies=soup.select('.txt-content')
 if len(bodies)!=1:raise DataContractError('missing_unique_GDP_body')
 found=[]
 for table in bodies[0].find_all('table'):
  trs=table.find_all('tr');active=False;carry=None;previous=None;observations={}
  for tr in trs:
   cells=tr.find_all(['td','th'],recursive=False);texts=[compact(c.get_text()) for c in cells]
   if texts==['','GDP环比增长速度(%)','GDP同比增长速度(%)']:active=True;continue
   if not active or len(texts)!=3:continue
   labels=list(re.finditer(r'(?:(20\d{2})年)?([1-4])季度',texts[0]))
   if not labels:continue
   if ''.join(m[0] for m in labels)!=texts[0]:raise DataContractError('ambiguous_GDP_quarter_labels')
   # Keep each number separated: Word HTML may pack several paragraphs in a cell.
   nums=[re.findall(r'-?\d+(?:\.\d+)?',c.get_text(' ',strip=True)) for c in cells[1:]]
   if not all(len(n)==len(labels) for n in nums):raise DataContractError('GDP_merged_cell_alignment')
   for i,label in enumerate(labels):
    if label[1]:carry=int(label[1])
    if carry is None:raise DataContractError('GDP_table_year_missing')
    quarter=int(label[2]);ordinal=carry*4+quarter
    if previous is not None and ordinal!=previous+1:raise DataContractError('GDP_table_quarters_not_sequential')
    previous=ordinal;observations[(carry,quarter)]=float(nums[1][i])
  if (y,q) in observations:
   if max(observations)!=(y,q):raise DataContractError('GDP_table_extends_beyond_release_period')
   found.append(observations[(y,q)])
 if not found or len(set(found))!=1:raise DataContractError('no_unambiguous_current_quarter_yoy_table')
 return y,q,found[0]
