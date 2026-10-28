"""M4의 평가 함수로 통합 뒤에도 기존 기준선이 유지되는지 확인한다.
이 교육용 Gold 데이터는 일반화 성능을 주장하지 않는다.
"""
from pathlib import Path
import json
from checker import load_rules,scan
from search_engine import build_documents,rank_tfidf,rank_bm25
from metrics import read_csv,inspect_evaluation,rank_evaluation
BASE=Path(__file__).resolve().parent
rules=load_rules(BASE/'data/rules.csv')
findings=scan((BASE/'data/sample.html').read_text(encoding='utf-8'),rules)
gold=read_csv(BASE/'gold/detection_gold.csv')
report={'detection':inspect_evaluation(gold,findings)}
docs=build_documents(data_dir=BASE/'data')
queries=read_csv(BASE/'gold/search_gold.csv')
report['search']={method:rank_evaluation(queries,engine,docs,k=2)
                  for method,engine in [('tfidf',rank_tfidf),('bm25',rank_bm25)]}
print(json.dumps({'detection':{'labeled_total':report['detection']['labeled_total'],
                   'exact_agreement':report['detection']['exact_agreement']},
                   'search':{k:v['macro'] for k,v in report['search'].items()}},
                 ensure_ascii=False,indent=2))
