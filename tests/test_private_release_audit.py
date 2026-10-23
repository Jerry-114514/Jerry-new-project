import unittest

from scripts.audit_private_release import scan


class PrivateReleaseAuditTests(unittest.TestCase):
    def needles(self):
        # Synthetic literals, never the actual private research seeds/records.
        return {'private_seed':{b'f'*64},'heldout_source_id':{b'proc-v1-'+b'1'*24},
                'heldout_input_identity':{b'012345abcdef-0-1'}}

    def test_known_markers_detected_without_returning_values(self):
        needles=self.needles()
        result=scan([('safe.txt',b'prefix '+b'f'*64+b' and proc-v1-'+b'1'*24+b' 012345abcdef-0-1')],needles)
        self.assertFalse(result['no_known_private_marker_exposure'])
        self.assertEqual(result['known_literal_marker_hits']['private_seed'],{'safe.txt':1})
        self.assertNotIn('f'*64,str(result))
        self.assertNotIn('1'*24,str(result))

    def test_marker_in_filename_is_redacted_and_private_roots_flagged(self):
        name='runs/proc-v1-'+'1'*24+'.json'
        result=scan([(name,b'')],self.needles())
        self.assertEqual(result['private_root_paths_tracked'],['runs/[redacted].json'])
        self.assertNotIn('1'*24,str(result))
        self.assertFalse(result['no_known_private_marker_exposure'])

    def test_public_commitments_and_unrelated_fixture_values_are_allowed(self):
        result=scan([('README.md',b'a'*64+b' proc-v1-'+b'2'*24),('LICENSE',b'fixture only')],self.needles())
        self.assertTrue(result['no_known_private_marker_exposure'])
        self.assertTrue(result['root_license_file_present'])
