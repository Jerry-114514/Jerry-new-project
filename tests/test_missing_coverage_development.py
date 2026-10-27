from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from build_missing_coverage_development import missing_views
from audit_view_coverage import audit
from build_execution_development import development_tasks
from intentlab.programmatic_labels import generate_labels
from intentlab.spec_reference import reference_files


class MissingCoverageDevelopmentTests(unittest.TestCase):
    def setUp(self):
        tasks,refs=development_tasks();self.task=deepcopy(tasks[0]);self.task['split']='train'
        self.reference=deepcopy(refs[0])

    def test_hidden_snapshot_is_violation_without_claiming_order_known(self):
        bundles=missing_views(self.task,self.reference)
        case=next(c for c,e,_,_ in bundles if e['scenario']=='hidden_snapshot_violation')
        labels=generate_labels([case],[self.task],{self.task['id']:self.reference})
        states={f['id']:f['status'] for f in labels[0]['findings']}
        self.assertIsNone(case['public']['observation']['events'])
        self.assertEqual(states['R_INPUT'],'violated');self.assertEqual(states['R_ORDER'],'unknown')

    def test_data_repair_is_correct_but_retained_report_count_is_stale(self):
        case,_,_,_=next(x for x in missing_views(self.task,self.reference) if x[1]['scenario']=='data_repair_stale_report')
        labels=generate_labels([case],[self.task],{self.task['id']:self.reference})
        states={f['id']:f['status'] for f in labels[0]['findings']}
        self.assertEqual(states['R_RESULT'],'satisfied');self.assertEqual(states['R_REPORT'],'violated')
        files=case['public']['observation']['files']
        self.assertEqual(files[self.task['report_path']]['output_rows'],len(files[self.task['output_path']])+1)

    def test_blocked_inputs_have_no_fake_successful_data_repair(self):
        self.task['inputs']['input/data.json'][0].pop(self.task['spec']['required_fields'][0])
        ref={'task_id':self.task['id'],'files':reference_files(self.task)}
        scenarios={x[1]['scenario'] for x in missing_views(self.task,ref)}
        self.assertEqual(scenarios,{'hidden_snapshot_violation','forbidden_extra_artifact'})

    def test_heldout_sources_are_rejected(self):
        for split in ('test','ood'):
            task=deepcopy(self.task);task['split']=split
            with self.assertRaises(ValueError):missing_views(task,self.reference)

    def test_auditor_counts_observed_scenarios_and_rejects_incomplete_labels(self):
        cases=[x[0] for x in missing_views(self.task,self.reference)]
        labels=generate_labels(cases,[self.task],{self.task['id']:self.reference})
        result=audit(cases,[self.task],labels)
        counts=result['counts']
        self.assertEqual(counts['hidden_history_snapshot_proves_input_violation'],1)
        self.assertEqual(counts['data_repair_leaves_stale_report'],1)
        self.assertEqual(counts['forbidden_extra_artifact_final'],1)
        self.assertEqual(counts['long_history_31_or_more_events'],0)
        self.assertEqual(result['by_split']['train'],counts)
        with self.assertRaises(ValueError):audit(cases,[self.task],labels[:-1])


if __name__=='__main__':unittest.main()
