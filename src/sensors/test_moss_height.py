import unittest
from unittest.mock import MagicMock, patch

from moss_height import LidMonitor, MossAggregate, MossHeight, WaterNoise


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
            self.assertEqual(sensor.read(), {"distance_cm": 8.2, "demo_data": False})
            measure.assert_called_once_with()
        sensor.close()

    def test_demo_uses_simulated_value_and_calculates_height(self):
        gpio = MagicMock()
        sensor = MossHeight(gpio, 1, 0, 5, empty_distance_cm=10,
                            demo_distance_cm=8, demo_sigma_cm=0.1)
        with patch('moss_height.TimestampUltrasonic._distance_cm', return_value=7), \
                patch('moss_height.random.gauss', return_value=8.05) as draw:
            fields = sensor.read()
        draw.assert_called_once_with(8, 0.1)
        self.assertAlmostEqual(fields['height_cm'], 1.95)
        self.assertTrue(fields['demo_data'])
        self.assertEqual(sensor.last_real_distance_cm, 7)
        sensor.close()
        gpio.gpio_claim_output.assert_called_once()
        gpio.gpio_free.assert_any_call(1, 5)

    def test_real_open_distance_overrides_demo_even_without_water_noise(self):
        sensor = MossHeight(MagicMock(), 1, 0, 5, empty_distance_cm=8,
                            demo_distance_cm=9, lid_threshold_cm=12)
        with patch('moss_height.TimestampUltrasonic._distance_cm', return_value=13):
            self.assertEqual(sensor.read()['distance_cm'], 13)
            self.assertFalse(sensor.read()['demo_data'])
        sensor.close()

    def test_demo_without_distance_still_reads_real_open_distance(self):
        sensor = MossHeight(MagicMock(), 1, 0, 5, demo_enabled=True)
        with patch('moss_height.TimestampUltrasonic._distance_cm', side_effect=[8, 13]):
            self.assertIsNone(sensor.read())
            self.assertEqual(sensor.read()['distance_cm'], 13)
        sensor.close()

    def test_demo_waits_for_water_data_and_uses_measured_standard_deviation(self):
        noise = WaterNoise()
        for index, value in enumerate([7.8, 7.9, 8.0, 8.1]):
            noise.add(index, value)
        self.assertIsNone(noise.sigma(4))
        sensor = MossHeight(MagicMock(), 1, 0, 5, demo_distance_cm=6)
        with patch('moss_height.TimestampUltrasonic._distance_cm', return_value=None):
            self.assertIsNone(sensor.read())
        noise.add(4, 8.2)
        sensor.demo_sigma_cm = noise.sigma(4)
        self.assertAlmostEqual(sensor.demo_sigma_cm, 0.158113883, places=6)
        with patch('moss_height.TimestampUltrasonic._distance_cm', return_value=None), \
                patch('moss_height.random.gauss', return_value=6.05) as draw:
            self.assertTrue(sensor.read()['demo_data'])
        draw.assert_called_once_with(6, sensor.demo_sigma_cm)
        self.assertIsNone(noise.sigma(65))

    def test_height_uses_its_own_reference_and_minute_median(self):
        sensor = MossHeight(MagicMock(), 1, 0, 5, empty_distance_cm=20.0)
        with patch("moss_height.TimestampUltrasonic._distance_cm", side_effect=[18.0, 17.0]), \
                patch("moss_height.time.monotonic", side_effect=[0, 5]):
            first = sensor.read()
            second = sensor.read()
        self.assertEqual(first["height_cm"], 2.0)
        self.assertEqual(second["height_cm"], 3.0)
        self.assertEqual(second["height_median_1m_cm"], 2.5)
        sensor.close()

    def test_lid_uses_three_valid_readings_per_sensor_and_keeps_state_on_failure(self):
        lid = LidMonitor(12)
        self.assertFalse(lid.update("moss1", 13))
        self.assertFalse(lid.update("moss1", None))
        self.assertFalse(lid.update("moss1", 13))
        self.assertFalse(lid.update("moss1", 13))
        self.assertTrue(lid.update("moss1", 13))
        self.assertTrue(lid.update("moss1", None))
        for _ in range(3):
            self.assertTrue(lid.update("moss2", 8))
        self.assertTrue(lid.update("moss1", 12))
        self.assertTrue(lid.update("moss1", 12))
        self.assertFalse(lid.update("moss1", 12))

    def test_lid_requires_each_open_sensor_to_close(self):
        lid = LidMonitor(12)
        for side in ("moss1", "moss2"):
            for _ in range(3):
                lid.update(side, 13)
        for _ in range(3):
            self.assertTrue(lid.update("moss1", 7))
        for _ in range(2):
            self.assertTrue(lid.update("moss2", 7))
        self.assertFalse(lid.update("moss2", 7))

    def test_aggregate_needs_both_recent_calibrated_sensors(self):
        aggregate = MossAggregate()
        self.assertIsNone(aggregate.update("moss1", 2.0, now=0))
        self.assertEqual(aggregate.update("moss2", 3.0, now=1), {"height_median_cm": 2.5})
        self.assertIsNone(aggregate.update("moss2", None, now=2))
        self.assertEqual(aggregate.update("moss2", 3.0, now=3), {"height_median_cm": 2.5})
        self.assertIsNone(aggregate.update("moss2", 3.0, now=15))


if __name__ == "__main__":
    unittest.main()
