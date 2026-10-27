"""Synthetic integrity fixtures, not observed formal statistical results."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import backup_statistics_reproduction as backup


class StatisticsBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.roots={k:self.root/k for k in ('supervision','analysis','replay')}
        for p in self.roots.values():p.mkdir()
        report={'scope':'formal','protocol_hash':'fixture-protocol','m8_complete':False,
                'comparisons':[{'fixture':n} for n in range(18)],'secondary_family_size':17}
        receipts=[]
        for name in ('analysis','replay'):
            path=self.roots[name]/'report.json';self.save(path,report)
            manifest={'kind':'frozen_statistics_analysis','scope':'formal','status':'completed',
                      'protocol_hash':'fixture-protocol','model_binding_hash':'fixture-binding',
                      'gold_or_references_reopened':False,'m8_complete':False,
                      'files_sha256':{'report.json':backup.sha(path)},'upstream_receipts':{'M7':'fixture-m7'}}
            manifest['receipt_hash']=backup.digest(manifest)
            self.save(self.roots[name]/'manifest.json',manifest);receipts.append(manifest['receipt_hash'])
        self.status={'kind':'frozen_statistics_reproduction_supervisor','status':'completed',
            'statistics_reproduction_complete':True,'canonical_reports_identical':True,
            'pid':123,'start_ticks':'fixture-ticks','driver_sha256':'fixture-driver','started_unix':1,
            'runtime_commit':'fixture-source','protocol_hash':'fixture-protocol','binding_hash':'fixture-binding',
            'statistics_receipt_hash':receipts[0],'replay_receipt_hash':receipts[1],
            'report_content_digest':backup.digest(report),'ablation_receipt_hash':'fixture-m7','m8_complete':False,
            'stages':[{'action':a,'status':'completed','exit_code':0,'child_pid':i+200}
                      for i,a in enumerate(('analysis','verify','replay','verify-replay'))]}
        self.status_path=self.roots['supervision']/'supervisor-status.json'
        self.save(self.status_path,self.status)
        self.save(self.roots['supervision']/'supervisor.claim.json',self.status)
        self.expected=backup.sha(self.status_path)

    @staticmethod
    def save(path,value):path.write_text(json.dumps(value),encoding='utf-8')

    def create(self,identity=lambda pid:{'proc_visible':False}):
        return backup.create(*self.roots.values(),self.expected,'fixture-driver','fixture-protocol',
                             'fixture-binding',self.root/'out',identity)

    def test_archive_then_independent_copy_verification_and_tamper_rejection(self):
        receipt=self.create();archive=self.root/'out/sealed-statistics.tar'
        copy=self.root/'off-host.tar';copy.write_bytes(archive.read_bytes())
        result=backup.verify_archive(copy,receipt)
        self.assertEqual(result['verified_members'],6)
        self.assertTrue(result['all_archive_members_reverified'])
        self.assertFalse(receipt['m8_complete']);self.assertFalse(receipt['off_host_copy_verified'])
        copy.write_bytes(copy.read_bytes()+b'changed')
        with self.assertRaises(ValueError):backup.verify_archive(copy,receipt)

    def test_live_worker_incomplete_or_boolean_exit_and_changed_status_rejected_before_copy(self):
        with self.assertRaises(ValueError):self.create(lambda pid:{'proc_visible':pid==201})
        for change in ({'status':'running'}, {'canonical_reports_identical':False}):
            status=deepcopy(self.status);status.update(change);self.save(self.status_path,status)
            self.expected=backup.sha(self.status_path)
            with self.assertRaises(ValueError):self.create()
        status=deepcopy(self.status);status['stages'][0]['exit_code']=False;self.save(self.status_path,status)
        self.expected=backup.sha(self.status_path)
        with self.assertRaises(ValueError):self.create()
        self.assertFalse((self.root/'out').exists())

    def test_changed_report_even_resealed_replay_cannot_pass(self):
        root=self.roots['replay'];report=json.loads((root/'report.json').read_text())
        report['comparisons'][0]['fixture']='changed';self.save(root/'report.json',report)
        manifest=json.loads((root/'manifest.json').read_text());manifest.pop('receipt_hash')
        manifest['files_sha256']['report.json']=backup.sha(root/'report.json')
        manifest['receipt_hash']=backup.digest(manifest);self.save(root/'manifest.json',manifest)
        self.status['replay_receipt_hash']=manifest['receipt_hash'];self.save(self.status_path,self.status)
        self.expected=backup.sha(self.status_path)
        with self.assertRaises(ValueError):self.create()
        self.assertFalse((self.root/'out').exists())


if __name__=='__main__':unittest.main()
