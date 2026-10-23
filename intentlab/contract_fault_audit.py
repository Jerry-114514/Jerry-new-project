"""Replay explicit fault expectations and isolated, declared labeler mutants."""
from collections import Counter
import hashlib
from pathlib import Path

from .contract_perturbations import verify_expectations
from . import programmatic_labels


MUTATIONS = {
    'ignore-restored-writes': ("changed or touched", "changed"),
    'ignore-write-order': ("validated and not bad_order", "validated"),
    'claim-hidden-order-safe': ("ordered = 'unknown'", "ordered = 'satisfied'"),
    'ignore-extra-artifacts': ("actual_paths == set(expected_data) and all(", "all("),
    'claim-reports-correct': ("report_ok = report_shape and report_path in snapshot and same(snapshot[report_path], wanted_report)", "report_ok = True"),
    'loose-json-types': ("same = lambda a, b: canonical(a) == canonical(b)", "same = lambda a, b: a == b"),
}


def audit_faults(cases, expectations, tasks, references):
    labels = programmatic_labels.generate_labels(cases, tasks, references)
    verify_expectations(labels, expectations)
    baseline = {row['case_id']: {r['id']: r['status'] for r in row['findings']} for row in labels}
    text = Path(programmatic_labels.__file__).read_text(encoding='utf-8')
    mutations = {}
    for name, (before, after) in MUTATIONS.items():
        if text.count(before) != 1:
            raise ValueError('Mutation no longer matches pinned implementation: ' + name)
        mutated = text.replace(before, after)
        namespace = {'__name__': 'intentlab._isolated_fault_mutant', '__package__': 'intentlab',
                     '__file__': programmatic_labels.__file__}
        # Compile only our own versioned evaluator with one declared edit; never
        # task text, model output or upstream data. Production globals untouched.
        exec(compile(mutated, '<declared-labeler-mutant:' + name + '>', 'exec'), namespace)
        findings = namespace['generate_labels'](cases, tasks, references)
        changed_cases, changed_items = 0, 0
        for row in findings:
            differences = sum(r['status'] != baseline[row['case_id']][r['id']] for r in row['findings'])
            changed_items += differences
            changed_cases += differences > 0
        mutations[name] = {'detected': changed_cases > 0, 'changed_cases': changed_cases,
            'changed_requirement_items': changed_items,
            'mutant_sha256': hashlib.sha256(mutated.encode()).hexdigest()}
    return {'scope': 'development_injected_faults_and_declared_mutants',
        'cases': len(cases), 'requirements_checked': sum(len(r['findings']) for r in labels),
        'scenarios': dict(Counter(r['scenario'] for r in expectations)),
        'scenario_assertion_disagreements': 0, 'mutations': mutations,
        'mutants_detected': sum(r['detected'] for r in mutations.values()),
        'mutants_total': len(mutations), 'human_evaluation_claim': False,
        'formal_proof': False,
        'warning': 'Only declared faults/mutants on existing development inputs. Not exhaustive verification, independent task count, held-out accuracy or a formal endpoint.'}
