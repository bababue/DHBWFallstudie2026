import unittest
from unittest.mock import MagicMock, patch
from water_level import WaterLevel


class WaterLevelTests(unittest.TestCase):
    def test_default_filter_waits_for_fifteen_samples_and_rejects_wave_peaks(self):
        sensor = WaterLevel(MagicMock(), 1, 6, 13, 8.3)
        with patch.object(sensor, '_distance_cm', side_effect=[5] * 12 + [5.8] * 3):
            for _ in range(14):
                self.assertNotIn('water_level_cm', sensor.read())
            result = sensor.read()
        self.assertEqual(result['measurement_stable'], 1)
        self.assertAlmostEqual(result['water_level_cm'], 3.3)
        self.assertEqual(result['distance_cm'], 5.8)

    def test_majority_alone_is_not_stable_enough(self):
        sensor = WaterLevel(MagicMock(), 1, 6, 13, 8.3)
        with patch.object(sensor, '_distance_cm', side_effect=[5] * 10 + [5.8] * 5):
            for _ in range(15):
                result = sensor.read()
        self.assertEqual(result['measurement_stable'], 0)
        self.assertNotIn('water_level_cm', result)

    def test_filters_outlier_and_keeps_raw_value(self):
        sensor = WaterLevel(MagicMock(), 1, 6, 13, 8.3, {'filter_messungen': 5})
        with patch.object(sensor, '_distance_cm', side_effect=[5, 5.02, 4.99, 5.01, 1]):
            for _ in range(4):
                self.assertNotIn('water_level_cm', sensor.read())
            result = sensor.read()
        self.assertEqual(result['distance_cm'], 1)
        self.assertAlmostEqual(result['water_level_cm'], 3.295)
        self.assertEqual(result['measurement_stable'], 1)

    def test_missing_echo_invalidates_filter(self):
        sensor = WaterLevel(MagicMock(), 1, 6, 13, 8.3, {'filter_messungen': 5})
        with patch.object(sensor, '_distance_cm', side_effect=[5]*5 + [None, 5]):
            for _ in range(5): sensor.read()
            self.assertIsNone(sensor.read())
            self.assertNotIn('water_level_cm', sensor.read())

    def test_upper_limit_uses_raw_reading_even_during_warmup(self):
        sensor = WaterLevel(MagicMock(), 1, 6, 13, 8.3, {'max_fuellhoehe_cm': 3})
        with patch.object(sensor, '_distance_cm', return_value=4):
            self.assertEqual(sensor.read()['max_level_reached'], 1)

    def test_timestamp_conversion(self):
        sensor = WaterLevel(MagicMock(), 1, 6, 13, 8.3)
        sensor._armed = True
        sensor._edge(0, 13, 1, 1_000_000)
        sensor._edge(0, 13, 0, 2_000_000)
        self.assertAlmostEqual(sensor._distance, 17.15)


if __name__ == '__main__': unittest.main()
