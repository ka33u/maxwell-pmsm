import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from audit_case import inspect
from compare_noload_exports import compare
from normalize_noload_emf import write_volts

class EvidenceChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.case = Path(self.tmp.name)
        self.conf = self.case / 'configuration.json'
        self.conf.write_text(json.dumps({'frequency_Hz': 50, 'cycles': 1, 'step_deg': 90}), encoding='utf8')
        h = hashlib.sha256(self.conf.read_bytes()).hexdigest()
        (self.case / 'run_case.py').write_text("if digest(os.path.join(case_dir,'configuration.json'))!='%s': raise Exception()\n" % h, encoding='utf8')
        self.log = self.case / 'run_result.txt'
        self.log.write_text('Validation=1\nAnalyze returned\nSaved solution before reports\nexported EMF\nNormal completion of simulation\nCLOSED; solution saved\n', encoding='utf8')
        (self.case / 'configured_noload_EXPLORATORY.aedt').write_bytes(b'project')
        results = self.case / 'configured_noload_EXPLORATORY.aedtresults'
        results.mkdir()
        # A placeholder only tests the evidence gate, not a valid Maxwell solve.
        (results / 'Full_Transient.asol').write_bytes(b'placeholder')
        self.csv = self.case / 'noload_EMF.csv'
        with self.csv.open('w', newline='') as f:
            w = csv.writer(f); w.writerow(['Time [ms]', 'InducedVoltage(Phase_A) [V]', 'InducedVoltage(Phase_B) [V]', 'InducedVoltage(Phase_C) [V]'])
            for t in (0, 5, 10, 15, 20): w.writerow([t, 1, 2, 3])
    def tearDown(self): self.tmp.cleanup()
    def set_config_and_runner(self, config):
        self.conf.write_text(json.dumps(config), encoding='utf8')
        h = hashlib.sha256(self.conf.read_bytes()).hexdigest()
        (self.case / 'run_case.py').write_text("if digest(os.path.join(case_dir,'configuration.json'))!='%s': raise Exception()\n" % h, encoding='utf8')
    def test_complete_and_integrals(self):
        data = inspect(self.case, 'noload')
        self.assertEqual(data['status'], 'evidence_consistent_not_physical_validation')
        self.assertEqual(data['files']['noload_EMF.csv']['last_cycle_rms'], [1., 2., 3.])
        self.assertEqual(data['files']['noload_EMF.csv']['end_s'], .02)
    def test_independent_export_compares_each_phase(self):
        exported = self.case / 'new.csv'
        data = self.csv.read_text()
        exported.write_text(data)
        self.assertTrue(compare(self.case, exported, 0)['matches'])
        exported.write_text(data.replace('[V]', '[mV]').replace(',1,2,3', ',1000,2000,3000'))
        self.assertTrue(compare(self.case, exported, 0)['matches'])
        exported.write_text(data.replace('[V]', '[mV]'))
        self.assertFalse(compare(self.case, exported, 1e-6)['matches'])
        exported.write_text(data.replace('10,1,2,3', '10,1,4,3'))
        result = compare(self.case, exported, 1e-6)
        self.assertFalse(result['matches'])
        self.assertEqual(result['max_abs_delta_V'], dict(A=0, B=2, C=0))
    def test_export_rejects_wrong_grid_units_and_aliases(self):
        with self.assertRaises(ValueError):
            compare(self.case, self.csv, 0)
        exported = self.case / 'new.csv'
        data = self.csv.read_text()
        for old, new in [('10,1,2,3', '11,1,2,3'), ('[V]', '[A]'), ('10,1,2,3', '10,1,nan,3')]:
            with self.subTest(new=new):
                exported.write_text(data.replace(old, new))
                with self.assertRaises(ValueError):
                    compare(self.case, exported, 0)
    def test_missing_solver_completion_rejected(self):
        self.log.write_text('Validation=1\nAnalyze returned\nCLOSED; solution saved', encoding='utf8')
        self.assertNotEqual(inspect(self.case, 'noload')['status'], 'evidence_consistent_not_physical_validation')
    def test_modified_configuration_rejected(self):
        self.conf.write_text(self.conf.read_text(encoding='utf8') + ' ', encoding='utf8')
        self.assertTrue(any('configuration hash' in x for x in inspect(self.case, 'noload')['errors']))
    def test_truncated_or_nonfinite_csv_rejected(self):
        contents = self.csv.read_text(encoding='utf8').splitlines()
        self.csv.write_text('\n'.join(contents[:-1]), encoding='utf8')
        self.assertTrue(any('sample count' in x for x in inspect(self.case, 'noload')['errors']))
        self.csv.write_text('\n'.join(contents).replace('5,1,2,3', '5,nan,2,3'), encoding='utf8')
        self.assertTrue(any('non-finite' in x for x in inspect(self.case, 'noload')['errors']))
    def test_results_missing_rejected(self):
        results = self.case / 'configured_noload_EXPLORATORY.aedtresults'
        (results / 'Full_Transient.asol').unlink()
        results.rmdir()
        self.assertTrue(any('results directory' in x for x in inspect(self.case, 'noload')['errors']))
    def test_empty_results_directory_rejected(self):
        results = self.case / 'configured_noload_EXPLORATORY.aedtresults'
        (results / 'Full_Transient.asol').unlink()
        (results / 'empty_subdir').mkdir()
        self.assertTrue(any('no nonempty regular files' in x for x in inspect(self.case, 'noload')['errors']))
        (results / 'empty_subdir' / 'empty.bin').write_bytes(b'')
        self.assertTrue(any('no nonempty regular files' in x for x in inspect(self.case, 'noload')['errors']))
    def test_fractional_cycle_count_rejected(self):
        config = json.loads(self.conf.read_text(encoding='utf8'))
        config['cycles'] = 1.5
        self.set_config_and_runner(config)
        data = inspect(self.case, 'noload')
        self.assertNotEqual(data['status'], 'evidence_consistent_not_physical_validation')
        self.assertTrue(any('integer cycle count' in x for x in data['errors']))
    def test_incomplete_source_lineage_pair_rejected(self):
        base = json.loads(self.conf.read_text(encoding='utf8'))
        for pair in ({'source_project': 'not-the-source.aedt'}, {'source_sha256': '0' * 64},
                     {'materials_source': 'materials.json'}, {'source_runner_sha256': '0' * 64}):
            with self.subTest(pair=pair):
                config = dict(base); config.update(pair); self.set_config_and_runner(config)
                data = inspect(self.case, 'noload')
                self.assertTrue(any('source lineage path/hash pair incomplete' in x for x in data['errors']))
                self.assertNotEqual(data['status'], 'evidence_consistent_not_physical_validation')
    def test_source_project_accepts_both_generator_hash_names(self):
        source = self.case / 'source.aedt'; source.write_bytes(b'source')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        base = json.loads(self.conf.read_text(encoding='utf8'))
        for hash_key in ('source_sha256', 'source_project_sha256'):
            with self.subTest(hash_key=hash_key):
                config = dict(base, source_project=str(source)); config[hash_key] = digest
                self.set_config_and_runner(config)
                self.assertTrue(inspect(self.case, 'noload')['source_lineage']['source_project']['matches'])
        config = dict(base, source_project=str(source), source_sha256=digest, source_project_sha256='0' * 64)
        self.set_config_and_runner(config)
        self.assertTrue(any('source lineage hash mismatch' in x for x in inspect(self.case, 'noload')['errors']))
    def test_bad_units_rejected(self):
        self.csv.write_text(self.csv.read_text(encoding='utf8').replace('[V]', '[A]'), encoding='utf8')
        self.assertTrue(any('voltage unit' in x for x in inspect(self.case, 'noload')['errors']))
    def test_saved_noload_millivolts_report_volts(self):
        data = self.csv.read_text().replace('[V]', '[mV]').replace(',1,2,3', ',1000,2000,3000')
        self.csv.write_text(data)
        result = inspect(self.case, 'noload')['files']['noload_EMF.csv']
        self.assertEqual(result['value_units'], 'V')
        self.assertEqual(result['last_cycle_rms'], [1., 2., 3.])
        normalized = self.case / 'converted.csv'
        self.assertEqual(write_volts(self.csv, normalized), 5)
        self.assertTrue(compare(self.case, normalized, 0)['matches'])
        with self.assertRaises(FileExistsError):
            write_volts(self.csv, normalized)
    def test_piecewise_linear_rms_differs_from_trapezoid_of_squares(self):
        rows = self.csv.read_text(encoding='utf8').splitlines()
        for i, value in enumerate((0, 2, 0, -2, 0), 1):
            t = (i-1)*5
            rows[i] = '%s,%s,%s,%s' % (t, value, value, value)
        self.csv.write_text('\n'.join(rows)+'\n', encoding='utf8')
        result = inspect(self.case, 'noload')['files']['noload_EMF.csv']
        self.assertAlmostEqual(result['last_cycle_mean'][0], 0.0)
        self.assertAlmostEqual(result['last_cycle_rms'][0], (4.0/3.0)**0.5)
        self.assertIn('piecewise-linear', result['integration_method'])
    def test_unicode_stdout_works_in_gbk_terminal(self):
        with self.log.open('a', encoding='utf8') as f: f.write('[warning] 🧲\n')
        env = os.environ.copy(); env['PYTHONIOENCODING'] = 'gbk'
        run = subprocess.run([sys.executable, str(Path(__file__).with_name('audit_case.py')), '--case', str(self.case), '--kind', 'noload'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(run.returncode, 0, run.stderr.decode('ascii', 'replace'))
        result = json.loads(run.stdout.decode('ascii'))
        self.assertTrue(any('🧲' in w for w in result['solver_warnings']))
    def test_solver_warning_promoted_to_general_warning_without_failure(self):
        with self.log.open('a', encoding='utf8') as f: f.write('[warning] BH curve needs review\n')
        result = inspect(self.case, 'noload')
        self.assertEqual(result['status'], 'evidence_consistent_not_physical_validation')
        self.assertEqual(len(result['solver_warnings']), 1)
        self.assertTrue(any('review solver_warnings' in warning for warning in result['warnings']))
    def test_changed_source_rejected(self):
        source = self.case / 'upstream.aedt'; source.write_bytes(b'changed')
        config = json.loads(self.conf.read_text(encoding='utf8'))
        config.update(source_project=str(source), source_sha256='0' * 64)
        self.conf.write_text(json.dumps(config), encoding='utf8')
        self.assertTrue(any('source lineage hash mismatch' in x for x in inspect(self.case, 'noload')['errors']))

if __name__ == '__main__': unittest.main()
