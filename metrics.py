"""A1-M4: 성능 평가 함수. 규칙 판정·검색 알고리즘을 이 파일에서 구현하지 않는다."""
from __future__ import annotations
import csv
from dataclasses import asdict, dataclass
from math import log2
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


@dataclass(frozen=True)
class BinaryScores:
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float
    recall: float
    f1: float
    accuracy: float


def binary_scores(truth: list[int], predicted: list[int]) -> BinaryScores:
    if not truth or len(truth) != len(predicted):
        raise ValueError('길이가 같은 비어 있지 않은 정답과 예측이 필요합니다.')
    if any(x not in (0, 1) for x in truth + predicted):
        raise ValueError('이진 평가에서는 0과 1만 사용합니다.')
    tp=sum(t == 1 and p == 1 for t,p in zip(truth,predicted))
    fp=sum(t == 0 and p == 1 for t,p in zip(truth,predicted))
    fn=sum(t == 1 and p == 0 for t,p in zip(truth,predicted))
    tn=sum(t == 0 and p == 0 for t,p in zip(truth,predicted))
    precision=tp/(tp+fp) if tp+fp else 0.0
    recall=tp/(tp+fn) if tp+fn else 0.0
    f1=2*precision*recall/(precision+recall) if precision+recall else 0.0
    return BinaryScores(tp,fp,fn,tn,precision,recall,f1,(tp+tn)/len(truth))


def inspect_evaluation(gold_rows: list[dict[str,str]], findings: list[dict]) -> dict:
    """실무: 사람이 검토한 (target, rule_id) 단위 정답과 검사 결과를 비교한다.

    평가용 정답에는 네 상태가 존재한다. passed/failed만 이진 지표로 계산하고,
    cantTell/inapplicable 및 예상과 다른 보류 처리를 별도 집계한다.
    """
    allowed={'passed','failed','cantTell','inapplicable'}
    found={(r['target'],r['rule_id']):r for r in findings}
    if len(found)!=len(findings):
        raise ValueError('결과에서 (target, rule_id)가 중복됩니다.')
    truth,predicted=[],[]
    rows=[]
    for gold in gold_rows:
        key=(gold['target'],gold['rule_id'])
        if gold['expected_outcome'] not in allowed:
            raise ValueError('정답 상태가 잘못되었습니다: '+str(key))
        if key not in found:
            raise LookupError('실제 판정 결과가 누락되었습니다: '+str(key))
        output=found[key]['outcome']
        if output not in allowed:
            raise ValueError('실제 검사기 결과가 잘못되었습니다: '+str(key))
        if gold['scope']!=found[key]['scope']:
            raise ValueError('표준/사내 규칙 범위 불일치: '+str(key))
        both_binary=(gold['expected_outcome'] in {'passed','failed'} and output in {'passed','failed'})
        if both_binary:
            truth.append(1 if gold['expected_outcome']=='failed' else 0)
            predicted.append(1 if output=='failed' else 0)
        rows.append({'target':key[0], 'rule_id':key[1], 'scope':gold['scope'],
                     'expected':gold['expected_outcome'], 'predicted':output,
                     'exact_match':gold['expected_outcome']==output,
                     'binary_scored':both_binary,
                     'note':gold['review_note']})
    eligible=sum(x['expected'] in ('passed','failed') for x in rows)
    matched=sum(x['exact_match'] for x in rows)
    binary=binary_scores(truth,predicted) if truth else None
    return {
        'labeled_total':len(rows), 'exact_agreement':matched/len(rows) if rows else 0,
        'review_expected':sum(x['expected']=='cantTell' for x in rows),
        'review_predicted':sum(x['predicted']=='cantTell' for x in rows),
        'not_applicable_expected':sum(x['expected']=='inapplicable' for x in rows),
        'definitive_gold':eligible,
        'binary_scored':len(truth),
        'decision_coverage':len(truth)/eligible if eligible else 0,
        'binary':asdict(binary) if binary else None,
        'rows':rows,
    }


def retrieval_scores(relevant: set[str], ranking: list[str], k: int) -> dict[str,float]:
    if k < 1:
        raise ValueError('k는 1 이상이어야 합니다.')
    if not relevant:
        raise ValueError('관련 문서가 0개인 질문은 별도 처리하며 Recall 계산에서 제외합니다.')
    if len(ranking)!=len(set(ranking)):
        raise ValueError('동일한 문서 ID가 검색 순위에 중복되었습니다.')
    top=ranking[:k]
    hits=[rid for rid in top if rid in relevant]
    recall=len(hits)/len(relevant)
    hit_rate=float(bool(hits))
    rr=next((1/i for i,r in enumerate(top,1) if r in relevant), 0.0)
    dcg=sum(1/log2(i+1) for i,r in enumerate(top,1) if r in relevant)
    idcg=sum(1/log2(i+1) for i in range(1,min(k,len(relevant))+1))
    return {'recall':recall,'hit':hit_rate,'rr':rr,'ndcg':dcg/idcg if idcg else 0.0}


def rank_evaluation(gold_rows: list[dict[str,str]], search, docs, *, k:int=3) -> dict:
    rows=[]
    document_ids={d.document_id for d in docs}
    for gold in gold_rows:
        relevant={x.strip() for x in gold['relevant_rule_ids'].split('|') if x.strip()}
        if not relevant <= document_ids:
            raise ValueError(f"현재 적용 규칙에 없는 정답 ID: {sorted(relevant-document_ids)}")
        ranked=search(gold['query'],docs,top_k=len(docs))
        ranking=[doc.document_id for doc,score in ranked]
        scores=retrieval_scores(relevant, ranking,k)
        rows.append({'qid':gold['qid'],'query':gold['query'],'relevant':sorted(relevant),
                     'ranking':ranking,'topk':ranking[:k],**scores,'note':gold['review_note']})
    if not rows:
        raise ValueError('평가 질문이 없습니다.')
    return {'k':k,'queries':len(rows),'macro':{name:sum(row[name] for row in rows)/len(rows)
            for name in ('recall','hit','rr','ndcg')},'rows':rows}
