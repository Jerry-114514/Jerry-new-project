from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from select_30h_coverage_data import match_quotas,categories,rank


class CoverageSelectionTests(unittest.TestCase):
    def test_matching_reroutes_flexible_sources_to_preserve_rare_category(self):
        first,second=sorted(('source-one','source-two'),key=rank)
        result=match_quotas({first:{'a','b'},second:{'a'}},{'a':1,'b':1})
        self.assertEqual(result,{first:'b',second:'a'})

    def test_infeasible_quota_is_rejected_without_dropping_a_source(self):
        with self.assertRaises(ValueError):match_quotas({'x':{'a'},'y':{'a'}},{'a':1,'b':1})
        with self.assertRaises(ValueError):match_quotas({'x':{'a'}},{'a':2})

    def test_input_order_does_not_change_assignment(self):
        a={'x':{'a','b'},'y':{'a','b'},'z':{'b'}}
        self.assertEqual(match_quotas(a,{'a':1,'b':2}),match_quotas(dict(reversed(list(a.items()))),{'b':2,'a':1}))

    def test_unknown_category_excludes_known_violations_and_long_requires_both(self):
        self.assertNotIn('unknown_only',categories({},set(),{'x':'unknown','y':'violated'}))
        self.assertIn('unknown_only',categories({},set(),{'x':'unknown','y':'satisfied'}))
        self.assertNotIn('long_rewrites',categories({}, {'long_history_31_or_more_events'},{'x':'satisfied'}))
        self.assertIn('long_rewrites',categories({}, {'long_history_31_or_more_events','multiple_data_and_report_rewrites'},{'x':'satisfied'}))


if __name__=='__main__':unittest.main()
