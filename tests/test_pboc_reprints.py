from pathlib import Path
import sys
from urllib.parse import parse_qs,urlparse
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pboc_reprint_links import search_item,parse_search

def sample(date='2010.04.12',total=12,host='www.mof.gov.cn'):
    return f'''<div>找到相关结果约{total}条</div><div class="list_search"><dl><dt><a href="http://{host}/zhengwuxinxi/caijingshidian/zyzfmhwz/201004/t20100412_286263.htm">金融统计报告</a></dt><span class="fr">{date}</span></dl></div>'''.encode()

def test_search_preserves_year_and_query_across_pages():
    item=search_item('货币供应量',2010)
    found,stats=parse_search(item,sample(),'raw.html')
    assert len(found)==2 and stats['total_hits']==12
    assert found[0]['original_result_url'].startswith('http:') and found[0]['url'].startswith('https:')
    query=parse_qs(urlparse(found[1]['url']).query)
    assert query['sStartTime']==['2010.01.01'] and query['searchword']==['货币供应量'] and query['page']==['2']
    assert 'available_at' not in found[0]

def test_year_filter_ignored_is_held():
    with pytest.raises(ValueError,match='ignored requested year'):
        parse_search(search_item('金融统计',2005),sample(),'raw.html')

def test_external_result_not_enqueued():
    found,stats=parse_search(search_item('金融统计',2010),sample(total=1,host='evil.example'),'raw.html')
    assert not found and stats['eligible_articles']==0

def test_bad_html_not_silently_treated_as_empty():
    with pytest.raises(ValueError,match='missing result count'):
        parse_search(search_item('金融统计',2005),b'<html>login</html>','raw.html')

def test_zero_result_and_pagination_cap_are_explicit():
    found,stats=parse_search(search_item('金融统计',2005),'<div>找到相关结果约0条</div><div class="list_search"></div>'.encode(),'raw.html')
    assert found==[] and stats['total_hits']==0
    found,stats=parse_search(search_item('金融统计',2010,page=100),sample(total=1200),'raw.html')
    assert stats['review_required'] and all(x['kind']=='article' for x in found)

def test_official_empty_template_is_recognized_without_accepting_generic_errors():
    content='<div class="list_search">很抱歉，没有找到和您的查询相匹配的结果。<br>您可以尝试更换检索词，重新检索。</div>'.encode()
    found,stats=parse_search(search_item('金融运行',2005),content,'raw.html')
    assert not found and stats['empty_result_template']

def test_dedicated_pboc_configuration_leaves_safe_manifest_unchanged(tmp_path,monkeypatch):
    import json
    import pull_source_archive as pull
    monkeypatch.setattr(pull,'ROOT',tmp_path);monkeypatch.setattr(pull,'BASE',tmp_path/'state')
    directory=tmp_path/'config';directory.mkdir()
    base={'sources':{'PBOC':{'seeds':[]},'SAFE':{'seeds':[],'index_pages_descending_from':2}}}
    (directory/'source_pull_tasks.json').write_text(json.dumps(base))
    (directory/'pboc_reprint_pull.json').write_text(json.dumps({'sources':{'PBOC':{'seeds':[],'note':'tested new source'}}}))
    pboc=pull.Worker('PBOC',False);safe=pull.Worker('SAFE',False)
    assert pboc.config_path.name=='pboc_reprint_pull.json' and pboc.spec['note']=='tested new source'
    assert safe.config_path.name=='source_pull_tasks.json' and safe.spec==base['sources']['SAFE']

def test_failed_flow_cannot_activate_source(tmp_path,monkeypatch):
    import hashlib,json
    import activate_pboc_reprints as activate
    monkeypatch.setattr(activate,'ROOT',tmp_path);monkeypatch.setattr(activate,'process_alive',lambda pid:False)
    config=tmp_path/'config';config.mkdir();base=config/'source_pull_tasks.json';base.write_text('{}')
    directory=tmp_path/'data/history_backfill/source_workers/pboc';directory.mkdir(parents=True)
    state={'config_sha256':hashlib.sha256(base.read_bytes()).hexdigest()}
    (directory/'state.json').write_text(json.dumps(state))
    out=tmp_path/'reports/v2/pboc_reprints';out.mkdir(parents=True)
    (out/'search_flow_tests.json').write_text(json.dumps({'results':[{'status':'FAILED'}]}))
    with pytest.raises(AssertionError):activate.main()
    assert not (config/'pboc_reprint_pull.json').exists()
    assert json.loads((directory/'state.json').read_text())==state
