"""A1-M6 CSV 통합: M2 검사 + M3 검색 + M5 정제 + 버전별 캐시.

규칙 기준 원본은 data/rules.csv 한 개이며, 구조는 data/rule_tree.csv로 연결한다.
근거 검색에서 나온 참고 규칙은 확정적 접근성 위반의 근거로 주장하지 않는다.
"""
from __future__ import annotations
from collections import Counter, OrderedDict
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import RLock
from checker import load_rules, scan
from search_engine import build_documents, rank_tfidf, rank_bm25
from cleaner import clean_text, PREPROCESS_VERSION

BASE = Path(__file__).resolve().parent

class InspectionService:
    def __init__(self, base: Path = BASE, cache_size: int = 64):
        self.base = Path(base)
        self.data_dir = self.base / 'data'
        self.cache_size = cache_size
        self._lock = RLock()
        self._cache: OrderedDict = OrderedDict()
        self._assets = None
        self._load(force=True)

    @staticmethod
    def digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def _load(self, force: bool = False):
        rule_digest = self.digest(self.data_dir/'rules.csv')
        tree_digest = self.digest(self.data_dir/'rule_tree.csv')
        asset_hashes = (rule_digest, tree_digest, PREPROCESS_VERSION)
        if force or asset_hashes != self._assets:
            # 오류가 발생하면 이전 자산으로 조용히 대체하지 않는다.
            rules = load_rules(self.data_dir/'rules.csv')
            docs = build_documents(data_dir=self.data_dir)
            by_id = {d.document_id:d for d in docs}
            if {r.rule_id for r in rules} != set(by_id):
                raise ValueError('검사 규칙과 검색 문서의 활성 ID 목록이 일치하지 않습니다.')
            # 각 규칙의 검색 본문만 M5의 정규화 적용, 원본 CSV는 손대지 않는다.
            from search_engine import SearchDoc
            self.docs = [SearchDoc(d.document_id, clean_text(d.text), {
                **d.metadata,'preprocess_version': PREPROCESS_VERSION,
            }) for d in docs]
            self.by_id = {d.document_id:d for d in self.docs}
            self.rules = rules
            self._assets = asset_hashes
            self._cache.clear()
        return self._assets

    def inspect(self, html: str, method='tfidf', k=2):
        if not html or len(html) > 20000:
            raise ValueError('HTML 입력은 1~20,000자여야 합니다.')
        if method not in ('tfidf','bm25') or not (1 <= k <= 5):
            raise ValueError('허용되지 않은 검색 옵션')
        with self._lock:
            rh, th, prep = self._load()
            hh = sha256(html.encode('utf-8')).hexdigest()
            key = (hh, rh, th, prep, method, k)
            if key in self._cache:
                self._cache.move_to_end(key)
                return deepcopy(self._cache[key]), True
            findings = scan(html, self.rules)
            search = rank_tfidf if method == 'tfidf' else rank_bm25
            review = []
            for finding in findings:
                if finding['outcome'] not in ('failed','cantTell'):
                    continue
                rid = finding['rule_id']
                doc = self.by_id.get(rid)
                if doc is None:
                    raise ValueError(f'근거 CSV에 규칙이 누락되었습니다: {rid}')
                # 정확한 rule_id 연결은 검색 점수와 무관하며, 관련 규칙 탐색은 별도 후보로 표시한다.
                direct = {'rule_id':rid, 'title':next(r.title for r in self.rules if r.rule_id==rid),
                          'source_file':'rules.csv','reference_url':finding['reference_url'],
                          'tree_path':doc.metadata.get('tree_path',''), 'status':doc.metadata['status'],
                          'rule_version':finding['rule_version']}
                query = clean_text(f"{direct['title']} {finding['message']} {finding['reason']}")
                neighbors = []
                for neighbor, score in search(query, self.docs, top_k=min(k+1,len(self.docs))):
                    if neighbor.document_id == rid: continue
                    neighbors.append({'rule_id':neighbor.document_id,
                         'title':next(r.title for r in self.rules if r.rule_id==neighbor.document_id),
                         'score':round(float(score),4), 'source_file':'rules.csv',
                         'tree_path':neighbor.metadata.get('tree_path',''),
                         'status':neighbor.metadata['status']})
                    if len(neighbors) >= k: break
                review.append({**finding, 'direct_rule':direct,
                               'related_rule_candidates':neighbors})
            counts = Counter(f['outcome'] for f in findings)
            result = {
                'input_sha256':hh, 'rule_hash':rh, 'tree_hash':th,
                'preprocess_version':prep, 'method':method, 'top_k':k,
                'rules_count':len(self.rules),
                'summary':{'rule_target_pairs':len(findings),
                           **{s:counts[s] for s in ('passed','failed','cantTell','inapplicable')},
                           'review_items':len(review),
                           'with_direct_rule':sum(bool(x['direct_rule']) for x in review)},
                'review_items':review, 'all_findings':findings,
            }
            self._cache[key] = deepcopy(result)
            if len(self._cache) > self.cache_size: self._cache.popitem(last=False)
            return result, False

    def cache_info(self):
        with self._lock:
            self._load()
            return {'entries':len(self._cache),
                    'rules_sha256':self._assets[0],
                    'tree_sha256':self._assets[1],
                    'preprocess_version':self._assets[2]}
