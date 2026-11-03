import unittest
from unittest.mock import MagicMock, patch
from water_level import WaterLevel
from measurements import DistanceFilter, WATER_SPREAD_CM, FILTER_SAMPLES


class WaterLevelTests(unittest.TestCase):
    def sensor(self):
        return WaterLevel(MagicMock(), 1, 6, 13, 8.3, 7)

    def test_fifteen_samples_reject_wave_peaks_but_keep_raw_value(self):
        sensor = self.sensor()
        with patch.object(sensor, '_distance_cm', side_effect=[5] * 12 + [5.8] * 3):
            for _ in range(14):
                self.assertNotIn('water_level_cm', sensor.read())
            result = sensor.read()
        self.assertEqual(result['measurement_stable'], 1)
        self.assertAlmostEqual(result['water_level_cm'], 3.3)
        self.assertEqual(result['distance_cm'], 5.8)

    def test_majority_alone_is_not_stable_enough(self):
        sensor = self.sensor()
        with patch.object(sensor, '_distance_cm', side_effect=[5] * 10 + [5.8] * 5):
            for _ in range(15): result = sensor.read()
        self.assertEqual(result['measurement_stable'], 0)
        self.assertNotIn('water_level_cm', result)

    def test_raw_upper_limit_is_not_hidden_during_warmup(self):
        sensor = self.sensor()
        with patch.object(sensor, '_distance_cm', return_value=1):
            self.assertEqual(sensor.read()['max_level_reached'], 1)

    def test_failure_and_sample_gap_reset_filter(self):
        for bad in [None, float('nan'), float('inf'), 0, 401, True]:
            f = DistanceFilter(WATER_SPREAD_CM)
            for t in range(FILTER_SAMPLES): f.update(5, t)
            self.assertIsNone(f.update(bad, 15))
            self.assertEqual(f.update(5, 16)['measurement_stable'], 0)
        f = DistanceFilter(WATER_SPREAD_CM)
        for t in range(FILTER_SAMPLES): f.update(5, t)
        self.assertEqual(f.update(5, 30)['measurement_stable'], 0)
