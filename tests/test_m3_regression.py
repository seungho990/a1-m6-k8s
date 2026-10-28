import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from search_engine import build_documents,rank_tfidf,rank_bm25,lookup_by_tree_node,tree_path,load_tree,load_rules

class SearchTests(unittest.TestCase):
    def test_same_m2_source_and_policy_filter(self):
        self.assertEqual(len(build_documents()),7)
        self.assertEqual(len(build_documents(include_proposed=True)),8)
        self.assertFalse(any(d.metadata['status']=='proposed' for d in build_documents()))
    def test_document_and_metadata_separated(self):
        d=next(d for d in build_documents() if d.document_id=='COMP-LINK-001')
        self.assertIn('reason:',d.text)
        self.assertNotIn('rule_version:',d.text)
        self.assertEqual(d.metadata['source_file'],'rules.csv')
        self.assertEqual(d.metadata['scope'],'company')
    def test_tree_lookup(self):
        d=lookup_by_tree_node('N_COMP_LINK_001')
        self.assertEqual(d.document_id,'COMP-LINK-001')
        self.assertIn('회사 작성 정책',d.metadata['tree_path'])
    def test_tfidf_ranked(self):
        x=rank_tfidf('이미지 alt 속성 확인',build_documents(),top_k=3)
        self.assertGreater(x[0][1],0)
        self.assertEqual(x[0][0].document_id,'IMG-001')
    def test_bm25_ranked(self):
        x=rank_bm25('이미지 alt 속성 확인',build_documents(),top_k=3)
        self.assertGreater(x[0][1],0)
        self.assertEqual(x[0][0].document_id,'IMG-001')
    def test_no_query(self):
        self.assertEqual(rank_tfidf('   ',build_documents()),[])
        self.assertEqual(rank_bm25('',build_documents()),[])
    def test_source_file_allowlist(self):
        self.assertRaises(ValueError,lookup_by_tree_node,'STD')
    def test_id_stability(self):
        self.assertEqual(len({x['rule_id'] for x in load_rules()}),7)

if __name__=='__main__':unittest.main()
