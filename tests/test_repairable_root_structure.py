from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_coverage_candidate_inputs import independent_repairable_roots
from build_execution_development import development_tasks


class RepairableRootStructureTests(unittest.TestCase):
    def test_dependency_expansion_is_not_an_independent_result_root(self):
        task=deepcopy(development_tasks()[0][0])
        rules=task['spec']['requirement_rules'];by_rule={v:k for k,v in rules.items()}
        task['spec']['dependencies']={rid:[] for rid in rules}
        self.assertEqual(independent_repairable_roots(task),2)
        task['spec']['dependencies'][by_rule['exact_outputs']]=[by_rule['report_counts']]
        self.assertEqual(independent_repairable_roots(task),1)

    def test_unknown_rule_kind_requires_review_instead_of_automatic_classification(self):
        task=deepcopy(development_tasks()[0][0])
        task['spec']['requirement_rules']['NEW']='new_rule_kind'
        with self.assertRaises(ValueError):independent_repairable_roots(task)


if __name__=='__main__':unittest.main()
