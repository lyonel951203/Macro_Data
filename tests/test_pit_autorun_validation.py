from datetime import datetime
import hashlib
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pit_autorun_validation import evidence_values,verify
from run_pit_history_autorun import jobs_for
from macro_pit.archive import RawArtifact
from macro_pit.timeutils import SHANGHAI


TITLE='2005年1月中国采购经理指数运行情况'
CONTENT=('''<title>2005年1月中国采购经理指数运行情况</title><body>2005/02/01 09:00
<div class="txt-content"><table><tr><td></td><td>PMI</td><td></td></tr>
<tr><td>生产</td><td>新订单</td><td>原材料库存</td><td>从业人员</td><td>供应商配送时间</td></tr>
<tr><td>2005年1月</td><td>51.3</td><td>53.5</td><td>52.6</td><td>48.8</td><td>48.3</td><td>49.2</td></tr>
</table></div></body>''').encode()


def setup_row():
    stamp=datetime(2005,2,1,9,tzinfo=SHANGHAI)
    row=dict(canonical_series_id='CN_PMI_MANUFACTURING',period='2005-01',value=51.3,pit_grade='A',available_at=stamp,
             release_at=stamp,frequency='M',unit='index',seasonal_adjustment='SA')
    artifact=RawArtifact('NBS','https://www.stats.gov.cn/x.html','x.html',hashlib.sha256(CONTENT).hexdigest(),'text/html',stamp,len(CONTENT))
    return row,artifact


def test_explicit_month_table_and_publication_agree():
    row,artifact=setup_row()
    accepted,held=verify(CONTENT,artifact,TITLE,'2005-02-01',[row],{row['canonical_series_id']})
    assert len(accepted)==1 and held==[]


@pytest.mark.parametrize('key,value', [('period','2005-02'),('value',53.5),('pit_grade','D'),('unit','pct_yoy'),
    ('frequency','Q'),('seasonal_adjustment','NSA'),('available_at',datetime(2005,1,31,tzinfo=SHANGHAI))])
def test_wrong_period_value_grade_unit_or_time_is_held(key,value):
    row,artifact=setup_row(); row[key]=value
    accepted,held=verify(CONTENT,artifact,TITLE,'2005-02-01',[row],{row['canonical_series_id']})
    assert not accepted and held


def test_migration_or_search_date_is_not_publication_date():
    row,artifact=setup_row()
    accepted,held=verify(CONTENT,artifact,TITLE,'2023-02-03',[row],{row['canonical_series_id']})
    assert not accepted and held


def test_unknown_column_order_is_not_accepted():
    altered=CONTENT.replace('原材料库存'.encode(),'其他库存'.encode())
    values,_=evidence_values(altered,TITLE)
    assert not values


def test_queue_spans_all_years_oldest_first():
    jobs=jobs_for(dict(start_year=2005,end_date='2026-07-31',terms=['PMI','GDP']))
    assert len(jobs)==44 and jobs[0]['start_date']=='2005-01-01' and jobs[-1]['end_date']=='2026-07-31'
    assert [j['start_date'] for j in jobs]==sorted(j['start_date'] for j in jobs)
