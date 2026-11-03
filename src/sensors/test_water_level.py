import unittest
from unittest.mock import MagicMock, patch
from water_level import WaterLevel
from moss_distance import MossDistance
from measurements import DistanceFilter, WATER_SPREAD_CM, FILTER_SAMPLES


class WaterLevelTests(unittest.TestCase):
    def test_configured_filter_applies_separate_spreads_to_both_sensor_types(self):
        settings = dict(messungen=5, mindestanteil_prozent=60,
                        wasser_streuung_cm=.06, moos_streuung_cm=.25, max_messpause_s=12)
        water = WaterLevel(MagicMock(), 1, 6, 13, 8.3, 7, filter_settings=settings)
        moss = MossDistance(MagicMock(), 1, 9, 11, filter_settings=settings)
        samples = [5, 5.05, 5.1, 5.25, 5.3]
        with patch.object(water, '_distance_cm', side_effect=samples), \
                patch.object(moss, '_distance_cm', side_effect=samples):
            for _ in samples:
                water_result = water.read()
                moss_result = moss.read()
        self.assertEqual(water_result['measurement_stable'], 0)
        self.assertEqual(water_result['distance_cm'], 5.3)
        self.assertEqual(moss_result['measurement_stable'], 1)
        self.assertEqual(moss_result['distance_filtered_cm'], 5.1)

    def test_configured_minimum_fraction_controls_stability(self):
        settings = dict(messungen=5, mindestanteil_prozent=60,
                        wasser_streuung_cm=.2, moos_streuung_cm=.3, max_messpause_s=12)
        samples = [5, 5, 5, 6, 6]
        for percent, expected in [(60, 1), (80, 0)]:
            settings['mindestanteil_prozent'] = percent
            sensor = WaterLevel(MagicMock(), 1, 6, 13, 8.3, 7, filter_settings=settings)
            with patch.object(sensor, '_distance_cm', side_effect=samples):
                for _ in samples:
                    result = sensor.read()
            self.assertEqual(result['measurement_stable'], expected)

    def test_percentage_boundary_is_exact(self):
        settings = dict(messungen=25, mindestanteil_prozent=56,
                        wasser_streuung_cm=.2, moos_streuung_cm=.3, max_messpause_s=12)
        sensor = WaterLevel(MagicMock(), 1, 6, 13, 8.3, 7, filter_settings=settings)
        with patch.object(sensor, '_distance_cm', side_effect=[5] * 14 + [6] * 11):
            for _ in range(25):
                result = sensor.read()
        self.assertEqual(result['measurement_stable'], 1)

    def test_configured_gap_resets_filter(self):
        settings = dict(messungen=3, mindestanteil_prozent=67,
                        wasser_streuung_cm=.2, moos_streuung_cm=.3, max_messpause_s=2)
        filtered = DistanceFilter.from_settings(settings, 'wasser')
        filtered.update(5, 0)
        filtered.update(5, 1)
        self.assertEqual(filtered.update(5, 3)['measurement_stable'], 1)
        self.assertEqual(filtered.update(5, 6)['measurement_stable'], 0)

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
