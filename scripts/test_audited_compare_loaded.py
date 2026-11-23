#!/usr/bin/env python3
"""Behavioral tests of audited comparisons; actual cases are optional fixtures."""
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import audited_compare_loaded as wrapper

SCRIPTS = Path(__file__).resolve().parent
PROJECT = SCRIPTS.parents[2]
COMPARATOR = PROJECT / 'compare_loaded_timestep.py'
AUDIT = SCRIPTS / 'audit_case.py'
CASES = PROJECT / 'two_motor_simulation_20261119'
HAS_REAL_CASES = (COMPARATOR.is_file() and
                  (CASES / '110kW_load_m62' / 'Torque.csv').is_file() and
                  (PROJECT / 'external_validation_v2/75kW_load_m62_step1p5/Torque.csv').is_file())


def run(coarse, fine, out, vary='timestep'):
    return subprocess.run([sys.executable, '-B', str(SCRIPTS / 'audited_compare_loaded.py'),
                           '--coarse', str(coarse), '--fine', str(fine), '--vary', vary,
                           '--comparator', str(COMPARATOR), '--audit-script', str(AUDIT), '--out', str(out)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def partial_copy(source, target, include_project=True):
    """Copy report fixtures/profile and optionally project, not actual result data."""
    target.mkdir()
    names = ['configuration.json', 'run_case.py', 'run_result.txt', 'Torque.csv',
             'Current.csv', 'Flux.csv', 'Voltage.csv', 'SolidLoss.csv']
    if include_project:
        names.append('configured_load_EXPLORATORY.aedt')
    for name in names:
        shutil.copy2(str(source / name), str(target / name))
    path = Path('configured_load_EXPLORATORY.aedtresults/Full_Transient.results')
    (target / path).mkdir(parents=True)
    for profile in (source / path).glob('*.profile'):
        shutil.copy2(str(profile), str(target / path / profile.name))


class UnitTests(unittest.TestCase):
    def test_output_rejects_inside_case_or_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); case = root / 'case'; case.mkdir()
            with self.assertRaisesRegex(ValueError, 'outside'):
                wrapper.check_output(case / 'new.json', [case])
            existing = root / 'used.json'; existing.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'already exists'):
                wrapper.check_output(existing, [case])
            self.assertEqual(wrapper.check_output(root / 'new.json', [case]), (root / 'new.json').resolve())

    def test_runner_normalization_requires_matching_unique_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); digest = 'a' * 64
            content = "if digest(os.path.join(case_dir,'configuration.json'))!='%s':pass\n" % digest
            (root / 'run_case.py').write_text(content, encoding='utf-8')
            info, normalized = wrapper.normalized_runner(root, digest)
            self.assertNotEqual(info['sha256'], info['normalized_sha256'])
            self.assertIn(b'0' * 64, normalized)
            with self.assertRaisesRegex(ValueError, 'configuration digest'):
                wrapper.normalized_runner(root, 'b' * 64)
            (root / 'run_case.py').write_text(content + content, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'exactly one'):
                wrapper.normalized_runner(root, digest)


@unittest.skipUnless(HAS_REAL_CASES, 'requires local 110/75 kW completed case fixtures')
class LocalCaseTests(unittest.TestCase):
    def setUp(self):
        # Generated outputs are outside the cases, under the D workspace.
        self.tmp = tempfile.TemporaryDirectory(prefix='audited-compare-test-', dir=str(PROJECT / 'skill_validation_20261120_round2'))
        self.root = Path(self.tmp.name)
        self.coarse = CASES / '110kW_load_m62'
        self.fine = PROJECT / 'external_validation_v1/110kW_load_m62_step1p5'

    def tearDown(self):
        self.tmp.cleanup()

    def assert_actual_pair(self, coarse, fine, vary, reference):
        output = self.root / 'passed.json'
        p = run(coarse, fine, output, vary)
        self.assertEqual(p.returncode, 0, p.stderr.decode('utf-8', 'replace'))
        data = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(data['status'], 'audited_exploratory_comparison_not_physical_validation')
        self.assertEqual(data['runners']['coarse']['normalized_sha256'], data['runners']['fine']['normalized_sha256'])
        self.assertTrue(data['audits']['coarse']['source_lineage']['source_project']['matches'])
        self.assertTrue(data['audits']['fine']['source_lineage']['source_project']['matches'])
        self.assertTrue(data['audits']['coarse']['solver_warnings'])
        self.assertEqual(data['tools']['comparator']['sha256'], hashlib.sha256(COMPARATOR.read_bytes()).hexdigest())
        historical = json.loads(reference.read_text(encoding='utf-8'))
        self.assert_report_equal(data['comparison']['reports'], historical['reports'])

    def assert_report_equal(self, actual, expected):
        if isinstance(expected, dict):
            self.assertEqual(actual.keys(), expected.keys())
            for key in expected:
                with self.subTest(field=key):
                    self.assert_report_equal(actual[key], expected[key])
        elif isinstance(expected, float):
            # Python 3.12 sums floats more accurately than the historical interpreter.
            self.assertTrue(math.isclose(actual, expected, rel_tol=1e-14, abs_tol=5e-13),
                            '%r differs from %r' % (actual, expected))
        else:
            self.assertEqual(actual, expected)

    def test_110kw_timestep(self):
        self.assert_actual_pair(self.coarse, self.fine, 'timestep', PROJECT / 'external_validation_v1/110kW_timestep_3deg_vs_1p5deg.json')

    def test_75kw_timestep(self):
        self.assert_actual_pair(CASES / '75kW_load_m62', PROJECT / 'external_validation_v2/75kW_load_m62_step1p5', 'timestep', PROJECT / 'external_validation_v2/75kW_timestep_3deg_vs_1p5deg.json')

    def test_110kw_band(self):
        self.assert_actual_pair(PROJECT / 'mesh_validation_110kW_20261119/band_0p5',
                                PROJECT / 'mesh_validation_110kW_20261119/band_0p25', 'band',
                                PROJECT / 'mesh_validation_110kW_20261119/band_comparison.json')

    def fixture(self, omit_project=False):
        coarse = self.root / 'coarse'; fine = self.root / 'fine'
        partial_copy(self.coarse, coarse, not omit_project)
        partial_copy(self.fine, fine, not omit_project)
        return coarse, fine

    def assert_rejected(self, coarse, fine, expected):
        output = self.root / 'rejected.json'
        p = run(coarse, fine, output)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn(expected, p.stderr.decode('utf-8', 'replace'))
        self.assertFalse(output.exists())

    def test_missing_project_is_rejected(self):
        coarse, fine = self.fixture(omit_project=True)
        self.assert_rejected(coarse, fine, 'saved AEDT project is missing or empty')

    def test_fatal_is_rejected(self):
        coarse, fine = self.fixture()
        with (fine / 'run_result.txt').open('a', encoding='utf-8') as stream:
            stream.write('\nFATAL isolated negative control\n')
        self.assert_rejected(coarse, fine, 'log contains FATAL or solver error')

    def test_changed_runner_is_rejected(self):
        coarse, fine = self.fixture()
        path = fine / 'run_case.py'; text = path.read_text(encoding='utf-8')
        needle = "d.Analyze('Reusable_Load')"
        self.assertEqual(text.count(needle), 1)
        path.write_text(text.replace(needle, "d.Analyze('Reusable_NoLoad')"), encoding='utf-8')
        self.assert_rejected(coarse, fine, 'runner contents differ')

    def test_unavailable_source_is_rejected(self):
        coarse, fine = self.fixture()
        for case in (coarse, fine):
            cfgpath = case / 'configuration.json'
            cfg = json.loads(cfgpath.read_text(encoding='utf-8'))
            cfg['source_project'] = r'Z:\not-present\source.aedt'
            cfgpath.write_text(json.dumps(cfg, indent=2) + '\n', encoding='utf-8')
            digest = hashlib.sha256(cfgpath.read_bytes()).hexdigest()
            runner = case / 'run_case.py'; text = runner.read_text(encoding='utf-8')
            # Avoid regex replacement ambiguity for digit-leading hex strings.
            pattern = r"(digest\(os\.path\.join\(case_dir,'configuration\.json'\)\)!=')([a-f0-9]{64})(')"
            text, count = re.subn(pattern, lambda m: m.group(1) + digest + m.group(3), text)
            self.assertEqual(count, 1)
            runner.write_text(text, encoding='utf-8')
        self.assert_rejected(coarse, fine, 'source project is unavailable or not verified')


if __name__ == '__main__':
    unittest.main()
