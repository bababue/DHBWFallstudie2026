import unittest
from unittest.mock import MagicMock, patch

from moss_height import MossAggregate, MossHeight


class MossHeightTests(unittest.TestCase):
    def test_echo_uses_edge_timestamps_and_releases_gpio(self):
        gpio = MagicMock()
        sensor = MossHeight(gpio, 1, 0, 5)
        gpio.gpio_claim_alert.assert_called_once_with(1, 5, gpio.BOTH_EDGES, gpio.SET_PULL_DOWN)
        sensor._armed = True
        sensor._edge(0, 5, 1, 1000000)
        sensor._edge(0, 5, 0, 1400000)
        self.assertAlmostEqual(sensor._distance, 6.86)
        sensor.close()
        gpio.callback.return_value.cancel.assert_called_once()
        gpio.gpio_free.assert_any_call(1, 5)

    def test_raw_distance_is_available_before_calibration(self):
        sensor = MossHeight(MagicMock(), 1, 0, 5)
        with patch("moss_height.TimestampUltrasonic._distance_cm", return_value=8.2) as measure:
            self.assertEqual(sensor.read(), {"distance_cm": 8.2})
            measure.assert_called_once_with()
        sensor.close()

    def test_missing_echo_does_not_generate_a_measurement(self):
        gpio = MagicMock()
        sensor = MossHeight(gpio, 1, 0, 5, empty_distance_cm=7)
        gpio.gpio_claim_output.assert_called_once_with(1, 0, 0)
        with patch('moss_height.TimestampUltrasonic._distance_cm', return_value=None):
            self.assertIsNone(sensor.read())
        sensor.close()

    def test_height_uses_its_own_reference_and_minute_median(self):
        sensor = MossHeight(MagicMock(), 1, 0, 5, empty_distance_cm=20.0)
        with patch("moss_height.TimestampUltrasonic._distance_cm", side_effect=[18.0, 17.0]), \
                patch("moss_height.time.monotonic", side_effect=[0, 5]):
            first = sensor.read()
            second = sensor.read()
        self.assertEqual(first["height_cm"], 8.0)
        self.assertEqual(second["height_cm"], 9.0)
        self.assertEqual(second["height_median_1m_cm"], 8.5)
        sensor.close()

    def test_height_is_measured_from_floor_and_clamped_at_floor(self):
        sensor = MossHeight(MagicMock(), 1, 0, 5, empty_distance_cm=6.94)
        with patch('moss_height.TimestampUltrasonic._distance_cm', side_effect=[5.44, 10.68812, 20]):
            self.assertAlmostEqual(sensor.read()['height_cm'], 7.5)
            self.assertAlmostEqual(sensor.read()['height_cm'], 2.25188)
            self.assertEqual(sensor.read()['height_cm'], 0)
        sensor.close()

    def test_aggregate_needs_both_recent_calibrated_sensors(self):
        aggregate = MossAggregate()
        self.assertIsNone(aggregate.update("moss1", 2.0, now=0))
        self.assertEqual(aggregate.update("moss2", 3.0, now=1), {"height_median_cm": 2.5})
        self.assertIsNone(aggregate.update("moss2", None, now=2))
        self.assertEqual(aggregate.update("moss2", 3.0, now=3), {"height_median_cm": 2.5})
        self.assertIsNone(aggregate.update("moss2", 3.0, now=15))


if __name__ == "__main__":
    unittest.main()
