"""Offline citation sufficiency for four explicitly encoded contract rules.

Background facts are the public contract (including original inputs and role
paths), trusted tool semantics, and history visibility/cardinality. Observation
values must be cited. A complete cited history may reconstruct the snapshot;
snapshot_paths supplies the complete current path inventory, not file values.

These are sufficient witness rules, not a complete natural-language entailment
system. Unknown is reported as an abstention, separately from citation support.
This supplementary evaluator never changes frozen scores or invokes a model.
"""
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import canonical, replay_events
from intentlab.execution_data import validate_references, validate_tasks
from intentlab.formal_data import STATUSES, evidence_catalog, validate_cases


VERSION = 'encoded_citation_sufficiency_v1'
RULES = {'preserve_inputs', 'validate_before_write', 'exact_outputs', 'report_counts'}


def same(left, right):
    return canonical(left) == canonical(right)


class EvidenceContext:
    def __init__(self, case, task, reference):
        validate_cases([case])
        validate_tasks([task])
        validate_references([reference], [task])
        for key in ('source_task_id', 'split', 'family', 'template_id'):
            if case[key] != task[key]:
                raise ValueError('Case/task grouping mismatch')
        public = case['public']
        expected = {'request': task['request'], 'inputs': task['inputs'],
                    'requirements': task['requirements'], 'execution_spec': task['spec']}
        if not same({key: public.get(key) for key in expected}, expected):
            raise ValueError('Case public contract differs from reference task')
        if reference['task_id'] != task['id'] or set(task['spec']['requirement_rules'].values()) != RULES:
            raise ValueError('Unsupported contract or mismatched reference')
        self.public, self.task, self.reference = deepcopy(public), deepcopy(task), deepcopy(reference)
        self.rules = self.task['spec']['requirement_rules']
        self.originals = self.public['inputs']
        self.snapshot = self.public['observation']['files']
        self.events = self.public['observation']['events']
        self.catalog = evidence_catalog(self.public)
        self.replayed = None
        if self.events is not None:
            self.replayed = replay_events(self.task, self.events)
            if not same(self.replayed.files, self.snapshot):
                raise ValueError('Visible tool history does not reconstruct the observed snapshot')
        self.blocked = any(field not in row for values in self.originals.values() for row in values
                           for field in self.task['spec']['required_fields'])

    def assess(self, finding):
        if not isinstance(finding, dict) or set(finding) != {'id', 'status', 'evidence'} \
                or finding.get('id') not in self.rules or finding.get('status') not in STATUSES:
            raise ValueError('A parsed finding with a supported ID and status is required')
        refs = finding['evidence']
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs) or len(set(refs)) != len(refs):
            raise ValueError('Unique string citations required')
        result = {'version': VERSION, 'requirement_id': finding['id'], 'rule': self.rules[finding['id']],
                  'predicted_status': finding['status'], 'citation_nonempty': bool(refs),
                  'citation_valid': all(ref in self.catalog for ref in refs),
                  'support_assessed': finding['status'] != 'unknown', 'entailed_status': None,
                  'supported': False}
        if not result['citation_valid']:
            return dict(result, verdict='invalid_reference', reason='citation_not_in_visible_catalog')
        if finding['status'] == 'unknown':
            return dict(result, verdict='abstention_not_scored', reason='abstention_is_not_a_known_status_certificate')
        if not refs:
            return dict(result, verdict='insufficient', reason='known_status_requires_nonempty_citations')
        selected = set(refs)
        event_ids = {event['index'] for event in self.events or [] if 'event:' + str(event['index']) in selected}
        full = self.events is not None and event_ids == set(range(len(self.events)))
        known = {ref[5:]: self.catalog[ref] for ref in selected if ref.startswith('file:')}
        inventory = set(self.snapshot) if 'snapshot_paths' in selected else None
        if full:
            known, inventory = self.replayed.files, set(self.replayed.files)
        visible = {event['index']: event for event in self.events or [] if event['index'] in event_ids}
        rule = self.rules[finding['id']]
        if rule == 'preserve_inputs':
            entailed, reason = self._inputs(known, inventory, visible, full)
        elif rule == 'validate_before_write':
            entailed, reason = self._order(visible, full)
        elif rule == 'exact_outputs':
            entailed, reason = self._outputs(known, inventory)
        else:
            entailed, reason = self._report(known, inventory)
        result.update(entailed_status=entailed, reason=reason,
                      full_history_cited=full, snapshot_inventory_known=inventory is not None)
        if entailed is None:
            return dict(result, verdict='insufficient')
        supported = entailed == finding['status']
        return dict(result, supported=supported, verdict='supported' if supported else 'contradicted')

    def _inputs(self, known, inventory, events, full):
        if any(path in known and not same(known[path], value) for path, value in self.originals.items()):
            return 'violated', 'cited_input_snapshot_changed'
        if inventory is not None and set(self.originals) - inventory:
            return 'violated', 'cited_inventory_shows_missing_input'
        if any(event['op'] in {'write', 'delete'} and event['path'] in self.originals for event in events.values()):
            return 'violated', 'cited_input_mutation_event'
        if full:
            return 'satisfied', 'complete_cited_history_has_no_input_mutation'
        return None, 'input_snapshot_or_partial_history_cannot_prove_never_written'

    def _order(self, events, full):
        if self.events is None:
            return None, 'hidden_history_cannot_certify_execution_order'
        for index, event in events.items():
            if event['op'] not in {'write', 'delete'}:
                continue
            report_exception = event['op'] == 'write' and event['path'] == self.task['report_path'] and self.blocked
            if self.blocked and not report_exception:
                return 'violated', 'cited_nonreport_mutation_with_missing_fields'
            preceding = [i for i, e in events.items() if i < index and e['op'] == 'validate']
            last_index = max(preceding) if preceding else -1
            if not set(range(last_index + 1, index)).issubset(events):
                continue  # Uncited intervening validation could change the state.
            last = events[last_index]['ok'] if last_index >= 0 else None
            allowed = last is False if report_exception else last is True
            if not allowed:
                return 'violated', 'cited_mutation_and_validation_prefix_violate_order'
        if full:
            validated = any(event['op'] == 'validate' and event['ok'] is (not self.blocked) for event in events.values())
            return ('satisfied', 'complete_cited_history_validates_before_mutations') if validated else \
                   ('violated', 'complete_cited_history_lacks_required_validation')
        return None, 'partial_history_cannot_certify_all_validation_order_constraints'

    def _outputs(self, known, inventory):
        expected = {path: value for path, value in self.reference['files'].items() if path != self.task['report_path']}
        excluded = set(self.originals) | {self.task['report_path']}
        if inventory is not None and inventory - excluded != set(expected):
            return 'violated', 'cited_inventory_has_missing_or_extra_output'
        if set(known) - excluded - set(expected):
            return 'violated', 'cited_unexpected_output_artifact'
        if any(path in known and not same(known[path], value) for path, value in expected.items()):
            return 'violated', 'cited_output_differs_from_independent_static_reference'
        if inventory is not None and all(path in known for path in expected):
            return 'satisfied', 'complete_output_inventory_and_values_match_static_reference'
        return None, 'output_values_or_complete_inventory_not_cited'

    def _report(self, known, inventory):
        report_path, output_path = self.task['report_path'], self.task['output_path']
        if inventory is not None and report_path not in inventory:
            return 'violated', 'cited_inventory_shows_missing_report'
        if not self.blocked:
            if inventory is not None and output_path not in inventory:
                return 'violated', 'cited_inventory_shows_missing_data_for_report'
            if output_path in known and not isinstance(known[output_path], list):
                return 'violated', 'cited_data_shape_cannot_supply_report_row_count'
        if report_path not in known:
            return None, 'report_value_not_cited'
        report = known[report_path]
        wanted = {'status': 'blocked' if self.blocked else 'ok', 'input_rows': sum(map(len, self.originals.values()))}
        if self.blocked:
            return ('satisfied', 'cited_blocked_report_matches_public_input_counts') if same(report, wanted) else \
                   ('violated', 'cited_blocked_report_has_wrong_shape_or_counts')
        if not isinstance(report, dict) or set(report) != {'status', 'input_rows', 'output_rows'} \
                or not same(report.get('status'), wanted['status']) or not same(report.get('input_rows'), wanted['input_rows']) \
                or type(report.get('output_rows')) is not int or report['output_rows'] < 0:
            return 'violated', 'cited_report_has_wrong_shape_status_or_count_type'
        if output_path not in known:
            return None, 'data_row_count_not_cited'
        wanted['output_rows'] = len(known[output_path])
        return ('satisfied', 'cited_report_and_data_have_correct_counts') if same(report, wanted) else \
               ('violated', 'cited_report_count_differs_from_cited_data')
