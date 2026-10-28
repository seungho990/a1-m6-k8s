"""A1-M3: A1-M2의 rules.csv와 rule_tree.csv를 재사용하는 검색 전용 모듈.

- 규칙 판정은 M2의 checker.py 책임이며 여기서는 수행하지 않는다.
- status=applied만 현행 규칙 검색에 포함한다(제안 정책은 기본 제외).
- 검색어와 문서를 같은 글자 n-gram 단위로 표현한다. 이는 M5의 형태소 분석을 대체하지 않는다.
- 검색 점수는 관련성 신호일 뿐 WCAG 위반 확정이나 '정답 확률'이 아니다.
"""
from __future__ import annotations
from collections import Counter
import csv
from dataclasses import dataclass
from math import log
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / 'data'
TEXT_FIELDS = ('title', 'description', 'reason', 'limitation')
META_FIELDS = ('rule_id','rule_version','status','scope','policy_id','wcag_ref','kwcag_ref','reference_url','effective_from')

@dataclass(frozen=True)
class SearchDoc:
    document_id: str
    text: str
    metadata: dict[str,str]


def load_rules(path: Path = DATA_DIR/'rules.csv', *, include_proposed: bool = False) -> list[dict[str,str]]:
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    # 규칙의 실존 여부와 문서 고유 ID를 확인한다.
    if len({r['rule_id'] for r in rows}) != len(rows):
        raise ValueError('rule_id 중복: 각 규칙에 고유 ID가 필요합니다.')
    return [r for r in rows if r['status'] == 'applied' or include_proposed]


def load_tree(path: Path = DATA_DIR/'rule_tree.csv') -> dict[str,dict[str,str]]:
    with path.open(encoding='utf-8-sig',newline='') as f:
        rows = list(csv.DictReader(f))
    ids = [r['node_id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('node_id 중복')
    nodes = {r['node_id']:r for r in rows}
    for r in rows:
        if r['parent_id'] and r['parent_id'] not in nodes:
            raise ValueError(f'잘못된 parent_id: {r["node_id"]}')
        if r['node_type'] == 'rule' and (r['file'] != 'rules.csv' or not r['rule_id']):
            raise ValueError('학습용 트리의 규칙 노드는 허용된 rules.csv와 rule_id만 참조합니다.')
    return nodes


def tree_path(node_id: str, nodes: dict[str,dict[str,str]]) -> str:
    parts, visited = [], set()
    while node_id:
        if node_id in visited:
            raise ValueError('부모-자식 관계 순환')
        if node_id not in nodes:
            raise ValueError('없는 트리 노드')
        visited.add(node_id)
        node = nodes[node_id]
        parts.append(node['label'])
        node_id = node['parent_id']
    return ' > '.join(reversed(parts))


def build_documents(*, include_proposed: bool = False, data_dir: Path | None = None) -> list[SearchDoc]:
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    rows = load_rules(root/'rules.csv', include_proposed=include_proposed)
    nodes = load_tree(root/'rule_tree.csv')
    # 트리의 '규칙 노드'만 연결하며, 트리에 없는 규칙도 검색은 가능하도록 독립 ID 유지.
    by_rule = {}
    for node in nodes.values():
        if node['node_type']=='rule':
            if node['rule_id'] in by_rule:
                raise ValueError(f'규칙에 중복 연결된 트리 노드: {node["rule_id"]}')
            by_rule[node['rule_id']] = node
    docs=[]
    for row in rows:
        node = by_rule.get(row['rule_id'])
        meta = {key:row.get(key,'') for key in META_FIELDS}
        meta['source_file'] = 'rules.csv'
        meta['node_id'] = node['node_id'] if node else ''
        meta['parent_id'] = node['parent_id'] if node else ''
        meta['tree_path'] = tree_path(node['node_id'],nodes) if node else ''
        # RAG용 텍스트와 filter/citation용 metadata는 다르다.
        text = '\n'.join(f'{field}: {row[field]}' for field in TEXT_FIELDS if row.get(field))
        docs.append(SearchDoc(row['rule_id'],text,meta))
    return docs


def char_ngrams(text: str, *, n_min: int = 2, n_max: int = 3) -> list[str]:
    """한국어 형태소 분석 전에 쓸 수 있는 단순 문자 조각; 기호와 공백을 보존."""
    text = ' '.join(text.split()).lower()
    return [text[i:i+n] for n in range(n_min,n_max+1)
            for i in range(len(text)-n+1)]


def rank_tfidf(query: str, documents: list[SearchDoc], *, top_k: int = 3) -> list[tuple[SearchDoc,float]]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    if not query.strip() or not documents:
        return []
    model = TfidfVectorizer(
        analyzer='char', ngram_range=(2,3),
        preprocessor=lambda text: ' '.join(text.split()).lower(),
    )
    matrix = model.fit_transform([d.text for d in documents])
    scores = cosine_similarity(model.transform([query]), matrix)[0]
    return sorted(((d,float(s)) for d,s in zip(documents,scores) if s>0),
                  key=lambda pair:(-pair[1],pair[0].document_id))[:top_k]


def rank_bm25(query: str, documents: list[SearchDoc], *, k1:float=1.5, b:float=0.75,
              top_k:int=3) -> list[tuple[SearchDoc,float]]:
    """Lucene 스타일 양수 IDF의 작은 BM25 직접 구현; rank_bm25와 수치가 다를 수 있다."""
    if not query.strip() or not documents:
        return []
    tokens=[char_ngrams(d.text) for d in documents]
    query_words=set(char_ngrams(query))
    n=len(tokens)
    avgdl=sum(len(t) for t in tokens)/n
    dfs=Counter(word for words in tokens for word in set(words))
    ranking=[]
    for doc, words in zip(documents,tokens):
        counter=Counter(words)
        length_normalize = 1-b+b*len(words)/avgdl
        score = 0.0
        for word in query_words:
            df=dfs[word]
            if df==0: continue
            idf=log(1+(n-df+0.5)/(df+0.5))
            tf=counter[word]
            if tf: score += idf*tf*(k1+1)/(tf+k1*length_normalize)
        if score>0: ranking.append((doc,score))
    return sorted(ranking,key=lambda pair:(-pair[1],pair[0].document_id))[:top_k]


def lookup_by_tree_node(node_id: str, *, include_proposed: bool=False) -> SearchDoc:
    nodes=load_tree()
    if node_id not in nodes or nodes[node_id]['node_type']!='rule':
        raise ValueError('규칙 노드를 선택하세요.')
    node=nodes[node_id]
    # CSV의 file 필드와 rule_id를 읽어 실제 행을 찾아 연결한다.
    if node['file']!='rules.csv':
        raise ValueError('알 수 없는 원본 파일 경로')
    docs={d.document_id:d for d in build_documents(include_proposed=include_proposed)}
    if node['rule_id'] not in docs:
        raise LookupError('현재 적용된 규칙이 없거나 규칙 ID를 찾을 수 없습니다.')
    return docs[node['rule_id']]

if __name__=='__main__':
    docs=build_documents()
    print('적용 규칙:',len(docs),'건 / 검토중 기본 제외')
    for engine in (rank_tfidf,rank_bm25):
        print('\n',engine.__name__)
        for doc, score in engine('링크 목적과 더보기 문구',docs):
            print(f'{doc.document_id:16} {score:8.4f} {doc.metadata["status"]} {doc.metadata["tree_path"]}')
