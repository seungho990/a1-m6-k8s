"""최신 A1 M2~M5 코드가 통합된 M6 검증. SQLite만 사용한다."""
from pathlib import Path
import shutil
from fastapi.testclient import TestClient
from pipeline import InspectionService
from db import Store
from checker import load_rules,scan
from search_engine import build_documents

BASE=Path(__file__).resolve().parents[1]

def test_m2_m3_same_active_rule_ids():
    rules=load_rules(BASE/'data/rules.csv')
    docs=build_documents(data_dir=BASE/'data')
    assert len(rules)==len(docs)==7
    assert {r.rule_id for r in rules}=={d.document_id for d in docs}
    assert all(d.metadata['status']=='applied' for d in docs)

def test_pipeline_direct_rule_and_scope():
    service=InspectionService(BASE)
    data,hit=service.inspect((BASE/'data/sample.html').read_text(encoding='utf-8'))
    assert not hit
    assert data['summary']['rule_target_pairs']==29
    findings={(x['target'],x['rule_id']):x['outcome'] for x in data['all_findings']}
    assert findings[('L02','LINK-002')]=='cantTell'
    assert findings[('L02','COMP-LINK-001')]=='failed'
    assert all(x['direct_rule']['rule_id']==x['rule_id'] for x in data['review_items'])
    assert all(x['direct_rule']['status']=='applied' for x in data['review_items'])
    assert all(x['rule_id']!='COMP-IMG-001' for x in data['review_items'])

def test_cache_and_edit_invalidate(tmp_path):
    d=tmp_path/'data'; d.mkdir()
    for name in ['rules.csv','rule_tree.csv']:
        shutil.copy2(BASE/'data'/name,d/name)
    service=InspectionService(tmp_path)
    h='<a href="/">더보기</a>'
    a,hit=service.inspect(h); assert not hit
    b,hit=service.inspect(h); assert hit and a==b
    old=a['rule_hash']
    p=d/'rules.csv'; p.write_text(p.read_text(encoding='utf-8-sig')+'\n',encoding='utf-8-sig')
    c,hit=service.inspect(h); assert not hit and c['rule_hash']!=old
    old_tree=c['tree_hash']
    p=d/'rule_tree.csv'; p.write_text(p.read_text(encoding='utf-8-sig')+'\n',encoding='utf-8-sig')
    e,hit=service.inspect(h); assert not hit and e['tree_hash']!=old_tree

def test_store_each_run_and_retrieve(tmp_path):
    db=Store(f'sqlite:///{tmp_path/"history.db"}')
    service=InspectionService(BASE)
    r1,hit1=service.inspect('<a href="/">더보기</a>')
    r2,hit2=service.inspect('<a href="/">더보기</a>')
    one=db.save(r1,hit1);two=db.save(r2,hit2)
    assert one!=two and hit2
    assert db.detail(two)['cache_hit']
    assert len(db.history())==2
    assert db.detail(two)['all_findings']

def test_real_api(tmp_path,monkeypatch):
    import api
    monkeypatch.setattr(api,'store',Store(f'sqlite:///{tmp_path/"api.db"}'))
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.delenv('BASIC_USER',raising=False)
    monkeypatch.delenv('BASIC_PASSWORD',raising=False)
    client=TestClient(api.app)
    assert client.get('/').status_code==200
    assert '검사 실행' in client.get('/').text
    assert client.get('/ready').status_code==200
    payload={'html':'<img src="a.jpg"><a href="/">더보기</a>','method':'bm25','k':2}
    a=client.post('/api/inspect',json=payload)
    assert a.status_code==200
    b=client.post('/api/inspect',json=payload)
    assert b.status_code==200
    assert b.json()['cache_hit'] is True
    assert a.json()['run_id']!=b.json()['run_id']
    assert len(client.get('/api/history').json())==2
    assert client.get('/api/history/'+a.json()['run_id']).status_code==200
    assert client.get('/api/cache').json()['preprocess_version']=='nfc-ws-v1'
    assert client.post('/api/inspect',json={'html':'','method':'tfidf'}).status_code==422
    assert client.post('/api/inspect',json={'html':'x','method':'invalid'}).status_code==422
