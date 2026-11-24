import math
import unittest

from winding_loading import phase_resistance_20c, round_wire_loading


class TestWindingLoading(unittest.TestCase):
    def test_phase_resistance_from_half_turn_and_parallel_paths(self):
        result = phase_resistance_20c(series_turns_per_path=50, mean_half_turn_mm=200,
                                     copper_area_mm2=2.5, parallel_paths=4)
        self.assertEqual(result["path_length_m"], 20.0)
        self.assertAlmostEqual(result["phase_R20_ohm"], 20 / (58 * 2.5 * 4))
        self.assertAlmostEqual(result["path_R20_ohm"], 4 * result["phase_R20_ohm"])

    def test_resistance_rejects_missing_copper_or_fractional_turns(self):
        args = dict(series_turns_per_path=2, mean_half_turn_mm=200, copper_area_mm2=1, parallel_paths=1)
        for key, value in (("series_turns_per_path", 2.5), ("mean_half_turn_mm", 0),
                           ("parallel_paths", 0), ("copper_area_mm2", float("nan"))):
            with self.subTest(key=key), self.assertRaises(ValueError):
                phase_resistance_20c(**{**args, key: value})

    def test_mixed_strands_and_parallel_paths(self):
        args = dict(phase_rms_A=24, parallel_paths=2, slots=24,
                    conductors_per_slot=10, bore_mm=100)
        result = round_wire_loading(wires=[(2, 1.0), (1, 2.0), (0, 3.0)], **args)
        self.assertAlmostEqual(result["copper_area_mm2"], 1.5*math.pi)
        self.assertAlmostEqual(result["J_A_mm2"], 8/math.pi)
        self.assertAlmostEqual(result["linear_A_cm"], 288/math.pi)
        self.assertAlmostEqual(result["AJ_A2_cm_mm2"], 2304/math.pi**2)

    def test_requires_active_copper(self):
        with self.assertRaises(ValueError):
            round_wire_loading(phase_rms_A=10, parallel_paths=1, slots=12,
                               conductors_per_slot=8, bore_mm=90, wires=[(0, 1.0)])
