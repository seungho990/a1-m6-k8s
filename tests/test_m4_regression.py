import unittest
from pathlib import Path
from checker import load_rules,scan
from search_engine import build_documents, rank_tfidf, rank_bm25,lookup_by_tree_node
from metrics import read_csv,binary_scores,retrieval_scores,inspect_evaluation,rank_evaluation

BASE=Path(__file__).resolve().parents[1]

class A1M4Tests(unittest.TestCase):
    def test_existing_rules_count(self):
        self.assertEqual(len(load_rules(BASE/'data/rules.csv')),7)
    def test_existing_checker_finding_count(self):
        f=scan((BASE/'data/sample.html').read_text(encoding='utf-8'),load_rules(BASE/'data/rules.csv'))
        self.assertEqual(len(f),29)
    def test_proposed_not_used_by_default(self):
        self.assertNotIn('COMP-LINK-003',{d.document_id for d in build_documents()})
    def test_tree_lookup_is_source_rule(self):
        self.assertEqual(lookup_by_tree_node('N_COMP_LINK_001').document_id,'COMP-LINK-001')
    def test_binary_manual_example(self):
        s=binary_scores([1]*5+[0]*5,[1,1,1,1,0,1,1,0,0,0])
        self.assertEqual((s.tp,s.fp,s.fn,s.tn),(4,2,1,3))
        self.assertAlmostEqual(s.f1,8/11)
    def test_retrieval_manual_example(self):
        s=retrieval_scores({'a','b','c'},['x','a','b'],3)
        self.assertAlmostEqual(s['recall'],2/3)
        self.assertAlmostEqual(s['rr'],0.5)
    def test_bad_k_rejected(self):
        with self.assertRaises(ValueError): retrieval_scores({'a'},['a'],0)
    def test_no_gold_relevant_raises(self):
        with self.assertRaises(ValueError): retrieval_scores(set(),['a'],2)
    def test_duplicate_ranking_rejected(self):
        with self.assertRaises(ValueError): retrieval_scores({'a'},['a','a'],2)
    def test_actual_inspection_gold(self):
        f=scan((BASE/'data/sample.html').read_text(encoding='utf-8'),load_rules(BASE/'data/rules.csv'))
        result=inspect_evaluation(read_csv(BASE/'gold/detection_gold.csv'),f)
        self.assertEqual(result['labeled_total'],22)
        self.assertEqual(result['review_expected'],4)
        self.assertEqual(result['binary_scored'],18)
    def test_real_search_q2_is_not_top1(self):
        docs=build_documents()
        gold=read_csv(BASE/'gold/search_gold.csv')
        q2=next(q for q in gold if q['qid']=='Q02')
        for engine in (rank_tfidf,rank_bm25):
            row=next(r for r in rank_evaluation([q2],engine,docs,k=2)['rows'])
            self.assertNotIn('COMP-LINK-001',row['ranking'][:1])
            self.assertIn('COMP-LINK-001',row['ranking'][:2])
    def test_search_gold_covered(self):
        docs=build_documents()
        gold=read_csv(BASE/'gold/search_gold.csv')
        for engine in (rank_tfidf,rank_bm25):
            s=rank_evaluation(gold,engine,docs,k=3)
            self.assertEqual(s['queries'],7)
            self.assertTrue(0<=s['macro']['recall']<=1)

if __name__=='__main__': unittest.main()
