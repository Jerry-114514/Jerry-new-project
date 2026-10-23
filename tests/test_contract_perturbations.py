from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_execution_development import development_tasks
from intentlab.contract_perturbations import perturbations, verify_expectations
from intentlab.programmatic_labels import generate_labels
from intentlab.contract_fault_audit import audit_faults


class ContractPerturbationTests(unittest.TestCase):
    def setUp(self):
        tasks, refs = development_tasks()
        self.tasks = [t for t in tasks if t['split'] in ('train', 'validation') and all(k in row for rows in t['inputs'].values() for row in rows for k in t['spec']['required_fields'])]
        ids = {t['id'] for t in self.tasks}
        self.refs = {r['task_id']: r for r in refs if r['task_id'] in ids}

    def test_fault_matrix_labels_and_preserved_grouping(self):
        cases, expected = perturbations(self.tasks, self.refs)
        labels = generate_labels(cases, self.tasks, self.refs)
        verify_expectations(labels, expected)
        self.assertEqual(len(cases), 12 * len(self.tasks))
        self.assertEqual({c['source_task_id'] for c in cases}, {t['source_task_id'] for t in self.tasks})
        self.assertEqual(sum(e['scenario'] in ('late-validation', 'missing-validation', 'restore-before-validation') for e in expected), 3 * len(self.tasks))

    def test_missing_duplicate_and_corrupted_labels_are_rejected(self):
        cases, expected = perturbations(self.tasks, self.refs)
        labels = generate_labels(cases, self.tasks, self.refs)
        duplicate = deepcopy(labels)
        duplicate[0]['findings'].append(deepcopy(duplicate[0]['findings'][0]))
        for faulty in (labels[:-1], labels + labels[:1], duplicate):
            with self.assertRaises(ValueError):
                verify_expectations(faulty, expected)
        faulty = deepcopy(labels)
        faulty[0]['findings'][1]['status'] = 'satisfied'
        with self.assertRaisesRegex(ValueError, 'expectation mismatch'):
            verify_expectations(faulty, expected)

    def test_rejects_heldout_tasks_before_fault_generation(self):
        task = deepcopy(self.tasks[0])
        task['split'] = 'test'
        with self.assertRaisesRegex(ValueError, 'test/OOD'):
            perturbations([task], {task['id']: self.refs[task['id']]})

    def test_declared_mutants_are_isolated_and_counterexamples_are_retained(self):
        cases, expected = perturbations(self.tasks, self.refs)
        before = generate_labels(cases, self.tasks, self.refs)
        report = audit_faults(cases, expected, self.tasks, self.refs)
        self.assertEqual(report['mutants_total'], 6)
        for name in ('ignore-restored-writes', 'ignore-write-order', 'claim-hidden-order-safe', 'ignore-extra-artifacts', 'claim-reports-correct'):
            self.assertTrue(report['mutations'][name]['detected'], name)
        self.assertEqual(generate_labels(cases, self.tasks, self.refs), before)
        self.assertFalse(report['formal_proof'])
