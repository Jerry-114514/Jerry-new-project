"""Bounded identity removal must not erase ordinary payload differences."""
from collections import Counter
import unittest

from scripts.audit_prior_public_inputs import containers, signatures


class PriorPublicInputsTests(unittest.TestCase):
    def test_changed_generated_identity_is_detected_only_in_registered_extra_modes(self):
        left = {'a.json': [{'rid': '012345abcdef-0-1', 'amount': 4}]}
        right = {'b.json': [{'rid': 'abcdef012345-9-7', 'amount': 4}]}
        a, b = signatures(left, True), signatures(right, True)
        self.assertNotEqual(a['paths_and_file_boundaries_removed'], b['paths_and_file_boundaries_removed'])
        self.assertEqual(a['generated_rid_and_paths_removed_groups_preserved'], b['generated_rid_and_paths_removed_groups_preserved'])
        self.assertNotEqual(a['generated_rid_removed_paths_preserved'], b['generated_rid_removed_paths_preserved'])
        self.assertEqual(len(signatures(left)), 3)

    def test_payload_types_order_and_other_identity_values_are_preserved(self):
        mode = 'generated_rid_paths_and_file_boundaries_removed'
        base = {'a': [{'rid': '012345abcdef-0-1', 'v': 1}, {'v': 2}]}
        changed = ({'a': [{'v': True}, {'v': 2}]}, {'a': [{'v': 2}, {'v': 1}]},
                   {'a': [{'rid': 'ordinary-user-id', 'v': 1}, {'v': 2}]},
                   {'a': [{'rid': 7, 'v': 1}, {'v': 2}]})
        for other in changed:
            self.assertNotEqual(signatures(base, True)[mode], signatures(other, True)[mode])

    def test_prompt_recursion_propagates_option_and_excludes_output_fields(self):
        payload = {'inputs': {'a': [{'rid': '012345abcdef-0-1', 'v': 1}]}}
        other = {'inputs': {'a': [{'v': 999}]}}
        import json
        counts = Counter()
        found = list(containers({'prompt': json.dumps(payload), 'gold': other, 'response': other}, counts, True))
        self.assertEqual(found, [signatures(payload['inputs'], True)])
        self.assertEqual(counts['recognized_input_containers'], 1)


if __name__ == '__main__':
    unittest.main()
