import unittest
from unittest.mock import MagicMock, patch
from moss_distance import MossDistance
from measurements import FILTER_SAMPLES


class MossDistanceTests(unittest.TestCase):
    def test_direct_distance_and_filter_without_height_calibration(self):
        gpio = MagicMock()
        sensor = MossDistance(gpio, 1, 0, 5)
        gpio.gpio_claim_alert.assert_called_once_with(1, 5, gpio.BOTH_EDGES, gpio.SET_PULL_DOWN)
        with patch.object(sensor, '_distance_cm', return_value=6.8):
            for _ in range(FILTER_SAMPLES):
                result = sensor.read()
        self.assertEqual(result, {'distance_cm': 6.8, 'distance_filtered_cm': 6.8, 'measurement_stable': 1})
        sensor.close()
        gpio.callback.return_value.cancel.assert_called_once()

    def test_missing_echo_invalidates_filter_and_never_fabricates_values(self):
        sensor = MossDistance(MagicMock(), 1, 0, 5)
        with patch.object(sensor, '_distance_cm', side_effect=[5] * FILTER_SAMPLES + [None, 5]):
            for _ in range(FILTER_SAMPLES): sensor.read()
            self.assertIsNone(sensor.read())
            self.assertEqual(sensor.read()['measurement_stable'], 0)

    def test_echo_uses_kernel_timestamps(self):
        sensor = MossDistance(MagicMock(), 1, 0, 5)
        sensor._armed = True
        sensor._edge(0, 5, 1, 1000000)
        sensor._edge(0, 5, 0, 1400000)
        self.assertAlmostEqual(sensor._distance, 6.86)
