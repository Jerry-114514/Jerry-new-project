import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from intentlab.research_statistics import (STRATIFIED_ANALYSIS_PLAN, comparison_registry,
                                          paired_cluster_statistics)


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('comparison_presentation', ROOT / 'scripts/render_statistics_comparisons.py')
presentation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(presentation)
FIXTURE = ROOT / 'examples/results/formal-m1o-candidate-statistics/matrix/statistics-analysis'


class PresentationTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp', prefix='comparison-presentation-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.report = presentation.read(FIXTURE / 'report.json')
        self.manifest = presentation.read(FIXTURE / 'manifest.json')

    def render(self, source=FIXTURE, out=None):
        return presentation.render(source, presentation.sha(source / 'manifest.json'),
                                   presentation.sha(source / 'report.json'), out or self.root / 'rendered', True)

    def test_all_registered_rows_seeds_and_undefined_values_retained(self):
        self.assertEqual(comparison_registry({'fixed_k_values': [1, 2, 3]}), presentation.registry())
        receipt = self.render()
        text = (self.root / 'rendered/STATISTICS.md').read_text(encoding='utf-8')
        for definition in presentation.registry():
            row = self.report['comparisons'][definition['id']]
            # Exactly one main row, then every paired seed row, with no filtering.
            self.assertEqual(1 + len(row['per_seed']), text.count('|' + definition['id'] + '|'))
        self.assertIn('|null|null|null|insufficient_clusters|', text)
        self.assertEqual(18, receipt['comparisons'])
        self.assertFalse(receipt['statistics_recomputed'])
        self.assertFalse(receipt['m8_complete'])
        with self.assertRaises(FileExistsError):
            self.render()

    def test_engineering_requires_explicit_option_and_trusted_hashes(self):
        with self.assertRaisesRegex(ValueError, 'manifest'):
            presentation.render(FIXTURE, presentation.sha(FIXTURE / 'manifest.json'),
                                presentation.sha(FIXTURE / 'report.json'), self.root / 'formal')
        with self.assertRaisesRegex(ValueError, 'trusted SHA256'):
            presentation.render(FIXTURE, '0' * 64, presentation.sha(FIXTURE / 'report.json'),
                                self.root / 'wrong-hash', True)
        self.assertFalse((self.root / 'formal').exists())
        self.assertFalse((self.root / 'wrong-hash').exists())

    def test_comparison_and_seed_omission_relabeling_and_null_rejected(self):
        for change in ('omit', 'extra', 'family', 'seed', 'effect', 'null_adjustment', 'invalid_p', 'nonfinite'):
            report = copy.deepcopy(self.report)
            row = report['comparisons']['RQ1/test']
            if change == 'omit':
                del report['comparisons']['RQ2/test']
            if change == 'extra':
                report['comparisons']['unregistered/test'] = row
            if change == 'family':
                row['definition']['family'] = 'secondary'
            if change == 'seed':
                row['per_seed'].pop()
            if change == 'effect':
                row['right_minus_left'] = 0.5
            if change == 'null_adjustment':
                report['comparisons']['RQ2/test']['holm_adjusted_p_value'] = 0.0
            if change == 'invalid_p':
                row['hypothesis_test']['p_value'] = -0.1
            if change == 'nonfinite':
                row['left'] = float('nan')
            with self.subTest(change=change), self.assertRaises(ValueError):
                presentation.validate(report, self.manifest, True)

    def test_no_arbitrary_task_text_export_and_fresh_directory_replay(self):
        # Unknown per-source fields may be present in an input report; the
        # presentation must not copy them or model text to its Markdown output.
        source = self.root / 'synthetic-input'
        source.mkdir()
        report = copy.deepcopy(self.report)
        report['private_task_details'] = {'synthetic-only-marker': 'synthetic model text'}
        (source / 'report.json').write_text(json.dumps(report), encoding='utf-8')
        manifest = copy.deepcopy(self.manifest)
        manifest['files_sha256'] = {'report.json': presentation.sha(source / 'report.json')}
        manifest['receipt_hash'] = presentation.digest({k: v for k, v in manifest.items() if k != 'receipt_hash'})
        (source / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        self.render(source, self.root / 'one')
        self.render(source, self.root / 'two')
        for name in ('STATISTICS.md', 'presentation-receipt.json'):
            self.assertEqual((self.root / 'one' / name).read_bytes(), (self.root / 'two' / name).read_bytes())
        self.assertNotIn('synthetic-only-marker', (self.root / 'one/STATISTICS.md').read_text(encoding='utf-8'))

    def test_duplicate_json_keys_rejected(self):
        path = self.root / 'duplicate.json'
        path.write_bytes(b'{"kind":"one","kind":"two"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            presentation.read(path)

    def test_nonzero_v2_format_keeps_effect_signs_intervals_and_p_values(self):
        # Entirely synthetic numeric records, not a formal experiment result.
        report, manifest = copy.deepcopy(self.report), copy.deepcopy(self.manifest)
        report.update(scope='formal', schema_version=3, analysis_plan=copy.deepcopy(STRATIFIED_ANALYSIS_PLAN))
        manifest['scope'] = 'formal'
        manifest['receipt_hash'] = presentation.digest({k: v for k, v in manifest.items() if k != 'receipt_hash'})
        for definition in presentation.registry():
            row = report['comparisons'][definition['id']]
            seeds = row['fixed_training_seeds']
            estimate = paired_cluster_statistics({'a': [0.2] * seeds, 'b': [0.5] * seeds},
                                                  {'a': [0.1] * seeds, 'b': [0.7] * seeds},
                                                  bootstrap_samples=100, strata={'a': 'A', 'b': 'A'})
            row.update(estimate)
            if definition['family'] == 'secondary':
                row['holm_adjusted_p_value'] = 1.0
        definitions = presentation.validate(report, manifest)
        text = presentation.markdown(report, definitions)
        row = report['comparisons']['RQ1/test']
        self.assertGreater(row['right_minus_left'], 0)  # Worse RQ1 direction remains.
        self.assertIn('|' + presentation.display(row['right_minus_left']) + '|', text)
        self.assertIn('[' + ', '.join(presentation.display(x) for x in row['percentile_95_interval']) + ']', text)
        self.assertIn('|1|null|exact_sign_assignments|', text)  # Primary raw p, no secondary correction.
        self.assertEqual(18, len(definitions))


if __name__ == '__main__':
    unittest.main()
