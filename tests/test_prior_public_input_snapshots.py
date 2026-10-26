"""Public byte-shape fixtures for historical snapshot extraction, without gold."""
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import audit_prior_public_input_snapshots as audit


class SnapshotExtractionTests(unittest.TestCase):
    def test_full_comparison_detects_a_previously_missed_public_snapshot(self):
        temporary_root = Path(__file__).resolve().parents[1] / 'tmp'
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as name:
            root = Path(name)
            self.assertTrue(root.resolve().is_relative_to(temporary_root.resolve()))
            inputs = {'input/fixture.json': [{'rid': 'abcdefabcdef-0-0', 'value': 7}]}
            tasks = [{'source_task_id': 'engineering-fixture-source', 'split': 'train', 'inputs': inputs}]
            current = root / 'tasks.jsonl'
            current.write_text(json.dumps(tasks[0]) + '\n', encoding='utf-8')
            raw = json.dumps({'final_state': {'files': inputs}}).encode('utf-8')
            blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            inventory = [{'blob_sha': blob, 'path_alias': 'examples/results/fixture.json', 'bytes': len(raw),
                          'parse_status': 'parsed', 'extraction_counts': {}}]
            inventory_path = root / 'inventory.json'
            inventory_path.write_text(json.dumps(inventory) + '\n', encoding='utf-8')

            class GitByteFixture:
                stdin = io.BytesIO()
                stdout = io.BytesIO((blob + ' blob ' + str(len(raw)) + '\n').encode() + raw + b'\n')
                def wait(self, timeout):
                    return 0
                def poll(self):
                    return 0

            with patch.object(audit.subprocess, 'check_output', return_value=(blob + ' examples/results/fixture.json\n').encode()), \
                    patch.object(audit.subprocess, 'Popen', return_value=GitByteFixture()):
                result = audit.audit(root, 'b' * 40, current, audit.legacy.digest(tasks), inventory_path,
                    hashlib.sha256(inventory_path.read_bytes()).hexdigest(), root / 'out')
            flags = json.loads((root / 'out/private-matches.json').read_text())
            self.assertEqual(result['match_records'], 6)
            self.assertEqual({r['extractor'] for r in flags}, {'input_array_snapshots'})
            self.assertEqual({r['source_task_id'] for r in flags}, {'engineering-fixture-source'})
            self.assertEqual(result['coverage']['previously_unrecognized_objects_with_input_array_snapshots'], 1)

    def test_previously_unrecognized_snapshot_matches_the_original_six_modes(self):
        inputs = {'input/fixture.json': [{'rid': 'abcdefabcdef-0-0', 'value': 7}]}
        value = {'final_state': {'files': {**inputs, 'output/result.json': [{'value': 999}]}}}
        self.assertEqual(list(audit.legacy.containers(value, Counter(), True)), [])
        counts = Counter()
        found = list(audit.snapshots(value, counts))
        self.assertEqual(found, [audit.legacy.signatures(inputs, True)])
        self.assertEqual(len(found[0]), 6)
        self.assertEqual(counts['recognized_input_snapshot_containers'], 1)

    def test_unsupported_second_input_cannot_create_a_partial_match(self):
        for other in ('[{"value":7}]', {'rows': []}, [7]):
            with self.subTest(other=other):
                value = {'files': {'input/a.json': [{'value': 7}], 'input/b.json': other}}
                counts = Counter()
                self.assertEqual(list(audit.snapshots(value, counts)), [])
                self.assertEqual(counts['snapshot_maps_with_unsupported_input_values'], 1)

    def test_answer_fields_and_output_only_maps_are_excluded(self):
        snapshot = {'files': {'input/a.json': [{'value': 7}]}}
        for key in audit.SKIP:
            with self.subTest(key=key):
                self.assertEqual(list(audit.snapshots({key: snapshot}, Counter())), [])
        self.assertEqual(list(audit.snapshots({'files': {'output/result.json': [{'value': 7}]}}, Counter())), [])

    def test_prompt_scope_remains_first_decodable_json_object(self):
        first = {'files': {'input/a.json': [{'value': 7}]}}
        second = {'files': {'input/a.json': [{'value': 999}]}}
        prompt = 'State: ' + json.dumps(first) + '\nLater content: ' + json.dumps(second)
        found = list(audit.snapshots({'prompt': prompt}, Counter()))
        self.assertEqual(found, [audit.legacy.signatures(first['files'], True)])


if __name__ == '__main__':
    unittest.main()
