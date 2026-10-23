"""Recorded metadata verification, not replay of private contract similarity."""
import hashlib
import json
from pathlib import Path
root=Path(__file__).resolve().parent
for name,expected in json.loads((root/'checksums.json').read_text()).items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,name
summary=json.loads((root/'summary.json').read_text())
overlap=json.loads((root/'overlap-summary.json').read_text())
assert summary['driver_sha256']==hashlib.sha256((root/'audit-driver.py').read_bytes()).hexdigest()
assert summary['cross_split_pairs']['test / train']['normalized_exact_pairs']==overlap['test_train_exact_pairs']==6
assert summary['cross_split_pairs']['test / train']['within_25_percent_row_edits']==overlap['test_train_near_pairs']==165
assert overlap['exact_train_overlap_test_sources']==5 and overlap['near_train_overlap_test_sources']==74
counts=overlap['stratum_source_counts']
assert counts['normalized_exact_train_overlap']+counts['no_normalized_exact_train_overlap']==counts['all_test']==200
assert counts['no_within_25pct_development_overlap']==126
assert overlap['no_task_removed_or_regenerated'] and not overlap['formal_test_candidate_selected']
assert overlap['no_model_outputs_or_gold_read'] and not summary['gold_read']
print('Recorded overlap metadata verified. Negative findings retained; no dataset approval.')
