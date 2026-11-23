import csv
import math
import tempfile
import unittest
from pathlib import Path
from ideal_winding_phasors import diagnose

ROOT = Path(__file__).resolve().parents[3]

class IdealWindingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'candidate.csv'
        src = ROOT / 'candidate_windings_72s12p' / 'candidate_39_conductors.csv'
        if not src.is_file(): self.skipTest('local candidate input unavailable')
        with src.open('r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f); self.headers = reader.fieldnames; self.rows = list(reader)
        self.write()
    def write(self):
        with self.path.open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=self.headers); w.writeheader(); w.writerows(self.rows)
    def evaluate(self): return diagnose(self.path, 72, 12, 5, 12)
    def reverse(self, predicate):
        for row in self.rows:
            if predicate(row):
                for key in ('upper_polarity', 'lower_polarity'):
                    row[key] = '+' if row[key] == '-' else '-'
        self.write()
    def test_real_balance_and_reversed_branch(self):
        a = self.evaluate(); self.assertLess(a['phases']['A']['max_deviation_over_mean'], 1e-10)
        self.reverse(lambda r: r['phase']=='A' and r['parallel_branch']=='1')
        b = self.evaluate(); self.assertAlmostEqual(b['phases']['A']['max_deviation_over_mean'], 2.2)
        for k in ('real','imag'):
            self.assertAlmostEqual(a['phases']['A']['branches'][0][k], -b['phases']['A']['branches'][0][k])
    def test_turn_weighting_and_phase_reversal(self):
        a = self.evaluate()
        for row in self.rows:
            if row['phase']=='A' and row['parallel_branch']=='1': row['series_turns_per_coil'] = str(2*int(row['series_turns_per_coil']))
        self.write(); b = self.evaluate()
        self.assertAlmostEqual(abs(complex(b['phases']['A']['branches'][0]['real'], b['phases']['A']['branches'][0]['imag'])), 2*a['phases']['A']['branches'][0]['magnitude'])
        self.reverse(lambda r: r['phase']=='A')
        c = self.evaluate()
        self.assertAlmostEqual(b['phases']['A']['max_deviation_over_mean'], c['phases']['A']['max_deviation_over_mean'])
        self.assertAlmostEqual(abs((c['phase_mean_relative_angles_deg']['A_to_B_deg']-b['phase_mean_relative_angles_deg']['A_to_B_deg']+180)%360-180), 180.)
    def test_zero_mean_ratio_is_undefined(self):
        self.reverse(lambda r: r['phase']=='A' and int(r['parallel_branch'])<=6)
        x = self.evaluate()['phases']['A']
        self.assertIsNone(x['max_deviation_over_mean']); self.assertIsNotNone(x['relative_deviation_note']); self.assertGreater(x['max_absolute_deviation'], 0)
    def test_wrong_pitch_rejected(self):
        with self.assertRaisesRegex(ValueError, 'pitch'): diagnose(self.path, 72, 12, 4, 12)

class SelfContainedTest(unittest.TestCase):
    def fixture12(self, path, inverted=(), doubled=()):
        fields = ('coil','phase','parallel_branch','upper_slot','upper_polarity','lower_slot','lower_polarity','series_turns_per_coil')
        with path.open('w', encoding='utf-8', newline='') as f:
            w = csv.writer(f); w.writerow(fields)
            for u in range(1,13):
                phase = 'ABC'[(u-1)%3]; branch = 1 if u <= 6 else 2
                pos = ((u-1)//3)%2 == 0
                if (phase,branch) in inverted: pos = not pos
                w.writerow([u, phase, branch, u, '+' if pos else '-', (u+2)%12+1,
                            '-' if pos else '+', 20 if (phase,branch) in doubled else 10])
    def test_balanced_reversal_turns_and_zero_mean_without_external_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'fixture.csv'
            self.fixture12(path); base = diagnose(path, 12, 4, 3, 2)
            self.assertLess(base['phases']['A']['max_deviation_over_mean'], 1e-10)
            self.fixture12(path, doubled=(('A',1),)); twice = diagnose(path, 12, 4, 3, 2)
            self.assertAlmostEqual(twice['phases']['A']['branches'][0]['magnitude'], 2*base['phases']['A']['branches'][0]['magnitude'])
            self.fixture12(path, inverted=(('A',1),)); inverted = diagnose(path, 12, 4, 3, 2)
            self.assertIsNone(inverted['phases']['A']['max_deviation_over_mean'])
            self.assertGreater(inverted['phases']['A']['max_absolute_deviation'], 0)
            self.fixture12(path, inverted=(('A',1),('A',2))); flipped = diagnose(path, 12, 4, 3, 2)
            self.assertAlmostEqual(flipped['phases']['A']['branches'][0]['real'], -base['phases']['A']['branches'][0]['real'])
            self.assertAlmostEqual(abs((flipped['phase_mean_relative_angles_deg']['A_to_B_deg']-base['phase_mean_relative_angles_deg']['A_to_B_deg']+180)%360-180), 180.)
    def test_six_slot_known_phasors_and_validation(self):
        fields = ('coil','phase','parallel_branch','upper_slot','upper_polarity','lower_slot','lower_polarity','series_turns_per_coil')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'fixture.csv'
            with path.open('w', encoding='utf-8', newline='') as f:
                w = csv.writer(f); w.writerow(fields)
                for u in range(1,7):
                    sign = '+' if u<=3 else '-'; other = '-' if sign=='+' else '+'
                    w.writerow([u, 'ABC'[(u-1)%3], 1, u, sign, (u+2)%6+1, other, 10])
            result = diagnose(path, 6, 2, 3, 1)
            self.assertAlmostEqual(result['phases']['A']['branches'][0]['magnitude'], 40.)
            self.assertAlmostEqual(result['phase_mean_relative_angles_deg']['A_to_B_deg'], 60.)
            with self.assertRaisesRegex(ValueError, 'pitch'): diagnose(path, 6, 2, 2, 1)

if __name__ == '__main__': unittest.main()
