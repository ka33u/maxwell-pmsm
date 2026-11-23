import csv
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('compare_mechanical_periods.py')
spec = importlib.util.spec_from_file_location('mechanical_period_compare', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class MechanicalPeriodComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'wave.csv'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, samples, header=('Time [ms]', 'Torque [Nm]')):
        with self.path.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(samples)

    def test_linear_drift_exact_mean_and_difference_rms(self):
        # 4 poles at 2 Hz -> 1 s mechanical period; x(t)=t gives Δx=1.
        self.write([(250*i, 0.25*i) for i in range(9)])
        result = mod.compare(self.path, 'Torque [Nm]', 4, 2., 2.)
        self.assertAlmostEqual(result['first_mean'], 0.5)
        self.assertAlmostEqual(result['second_mean'], 1.5)
        self.assertAlmostEqual(result['difference_rms'], 1.)
        self.assertAlmostEqual(result['difference_max_abs_sampled'], 1.)
        self.assertEqual(result['windows_s'], [[0., 1.], [1., 2.]])
        self.assertEqual(len(result['source_sha256']), 64)
        self.assertEqual(result['status'], 'sampled_period_comparison_not_convergence')

    def test_12_pole_150_hz_periodic_signal(self):
        # Realistic 3 electric-degree sampling: 720 points per mechanical turn.
        dt = (6. / 150.) / 720
        samples = [(1000*i*dt, 10 + math.sin(2*math.pi*i/720)) for i in range(1441)]
        self.write(samples)
        result = mod.compare(self.path, 'Torque [Nm]', 12, 150., 0.08)
        self.assertEqual(result['samples_per_period_including_endpoints'], 721)
        self.assertAlmostEqual(result['mechanical_period_s'], .04)
        self.assertAlmostEqual(result['first_mean'], 10., places=11)
        self.assertLess(result['difference_rms'], 1e-12)

    def test_missing_sample_rejected(self):
        self.write([(250*i, float(i)) for i in range(9) if i != 5])
        with self.assertRaisesRegex(ValueError, 'uniformly continuous'):
            mod.compare(self.path, 'Torque [Nm]', 4, 2., 2.)

    def test_insufficient_coverage_reports_synchronous_assumption_and_no_output(self):
        # 4 poles at 2 Hz implies a 1 s period only for synchronous speed.
        # 1.5 s of data is 0.5 s short of two complete mechanical periods.
        self.write([(250*i, 0.25*i) for i in range(7)])
        out = Path(self.temp.name) / 'insufficient.json'
        proc = subprocess.run([sys.executable, str(SCRIPT), '--csv', str(self.path),
                               '--column', 'Torque [Nm]', '--poles', '4',
                               '--frequency-hz', '2', '--end-time-s', '1.5', '--out', str(out)],
                              capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('insufficient data for two complete mechanical periods', proc.stderr)
        self.assertIn('available coverage 1.5 s, required 2 s, shortfall 0.5 s', proc.stderr)
        self.assertIn('assuming electrical frequency and pole count imply synchronous mechanical speed', proc.stderr)
        self.assertFalse(out.exists())

    def test_insufficient_coverage_uses_selected_end_and_initial_time(self):
        # Later rows do not count when the caller selected an earlier end time.
        self.write([(1000*(10 + .25*i), .25*i) for i in range(13)])
        with self.assertRaisesRegex(ValueError, 'available coverage 1.5 s, required 2 s, shortfall 0.5 s'):
            mod.compare(self.path, 'Torque [Nm]', 4, 2., 11.5)

    def test_unaligned_period_and_end_are_rejected(self):
        self.write([(250*i, float(i)) for i in range(13)])
        with self.assertRaisesRegex(ValueError, 'integer number'):
            mod.compare(self.path, 'Torque [Nm]', 4, 3., 2.)
        with self.assertRaisesRegex(ValueError, 'not an available sample'):
            mod.compare(self.path, 'Torque [Nm]', 4, 2., 2.1)

    def test_unspecified_or_conflicting_time_unit_is_rejected(self):
        self.write([(0, 0), (1, 1), (2, 2), (3, 3)], ('Time', 'Value'))
        with self.assertRaisesRegex(ValueError, 'specify --time-unit'):
            mod.compare(self.path, 'Value', 2, 1., 2.)
        result = mod.compare(self.path, 'Value', 2, 1., 2., time_unit='s')
        self.assertEqual(result['difference_rms'], 1.)
        self.write([(0, 0), (1, 1), (2, 2)], ('Time [ms]', 'Value'))
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            mod.compare(self.path, 'Value', 2, 1., 0.002, time_unit='s')

    def test_unknown_explicit_header_units_cannot_be_overridden(self):
        # These numeric time values are nanoseconds, not seconds. An override
        # must not silently report 2 ns as two full seconds of waveform.
        for header in ('Time [ns]', 'Time [min]', 'Time []', 'Time [seconds]'):
            with self.subTest(header=header):
                self.write([(0, 0), (1, 1), (2, 2)], (header, 'Value'))
                for supplied in (None, 's'):
                    with self.assertRaisesRegex(ValueError, 'unsupported time unit in time-column header'):
                        mod.compare(self.path, 'Value', 2, 1., 2., time_unit=supplied)

    def test_unknown_header_unit_cli_fails_without_output(self):
        self.write([(0, 0), (1, 1), (2, 2)], ('Time [ns]', 'Value'))
        out = Path(self.temp.name) / 'incorrect_result.json'
        process = subprocess.run([sys.executable, str(SCRIPT), '--csv', str(self.path),
                                  '--column', 'Value', '--poles', '2', '--frequency-hz', '1',
                                  '--end-time-s', '2', '--time-unit', 's', '--out', str(out)],
                                 capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('unsupported time unit in time-column header', process.stderr)
        self.assertFalse(out.exists())

    def test_explicit_time_column_with_malformed_unit_rejected(self):
        self.write([(0, 0), (1, 1), (2, 2)], ('Elapsed [ms', 'Value'))
        with self.assertRaisesRegex(ValueError, 'malformed time-column unit header'):
            mod.compare(self.path, 'Value', 2, 1., 2., time_column='Elapsed [ms', time_unit='s')

    def test_unicode_microsecond_headers_are_understood(self):
        for sign in ('µ', 'μ'):
            with self.subTest(sign=sign):
                self.write([(i*250000, i*.25) for i in range(9)], ('Time [' + sign + 's]', 'Value'))
                result = mod.compare(self.path, 'Value', 4, 2., 2.)
                self.assertAlmostEqual(result['difference_rms'], 1.)
                self.assertAlmostEqual(result['sample_step_s'], .25)

    def test_help_and_unicode_output_path_on_gbk_console(self):
        env = dict(os.environ, PYTHONIOENCODING='gbk')
        help_result = subprocess.run([sys.executable, str(SCRIPT), '--help'], env=env,
                                     capture_output=True)
        self.assertEqual(help_result.returncode, 0, help_result.stderr.decode('gbk', errors='replace'))
        self.assertIn(b'--time-unit {s,ms,us}', help_result.stdout)
        self.write([(250*i, .25*i) for i in range(9)])
        out = Path(self.temp.name) / 'result_\U0001f9ed.json'
        result = subprocess.run([sys.executable, str(SCRIPT), '--csv', str(self.path),
                                 '--column', 'Torque [Nm]', '--poles', '4',
                                 '--frequency-hz', '2', '--end-time-s', '2', '--out', str(out)],
                                env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode('gbk', errors='replace'))
        self.assertTrue(out.is_file())
        self.assertIn(b'\\U0001f9ed', result.stdout)

    def test_actual_110kw_two_electric_cycles_are_not_two_mechanical_turns(self):
        root = SCRIPT.resolve().parents[3]
        real = root / 'two_motor_simulation_20261119' / '110kW_load_m62' / 'Torque.csv'
        if not real.is_file():
            self.skipTest('workspace Maxwell result is unavailable')
        with real.open('r', encoding='utf-8-sig', newline='') as stream:
            records = list(csv.reader(stream))
        end_s = float(records[-1][0]) / 1000.
        out = Path(self.temp.name) / 'must_not_exist.json'
        process = subprocess.run([sys.executable, str(SCRIPT), '--csv', str(real),
                                  '--column', 'Moving1.Torque [NewtonMeter]',
                                  '--poles', '12', '--frequency-hz', '150',
                                  '--end-time-s', str(end_s), '--out', str(out)],
                                 capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('insufficient data for two complete mechanical periods', process.stderr)
        self.assertFalse(out.exists())

    def test_previous_8_pole_full_turn_result_matches_independent_audit(self):
        root = SCRIPT.resolve().parents[3]
        real = root / 'outer8_38sh_100c_53p7A_two_revolutions_recovery' / 'Torque_reopened.csv'
        previous = root / 'outer8_38sh_100c_53p7A_two_revolutions' / 'adjacent_turns.json'
        if not real.is_file() or not previous.is_file():
            self.skipTest('workspace recovered full-turn reference is unavailable')
        result = mod.compare(real, 'Moving1.Torque [NewtonMeter]', 8, 100., .09)
        expected = json.loads(previous.read_text(encoding='utf-8'))['reports']['Torque']['Moving1.Torque']
        self.assertAlmostEqual(result['first_mean'], expected['first']['mean'], places=8)
        self.assertAlmostEqual(result['second_mean'], expected['second']['mean'], places=8)
        self.assertAlmostEqual(result['difference_rms'], expected['second_minus_first']['rms_linear_interpolation'], places=10)
        self.assertAlmostEqual(result['difference_max_abs_sampled'], expected['second_minus_first']['max_abs_at_samples'], places=9)


if __name__ == '__main__':
    unittest.main()
