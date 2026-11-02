import unittest
from unittest.mock import MagicMock, patch

from water_level import WaterLevel


class WaterLevelTests(unittest.TestCase):
    def test_median_ignores_missing_echo_and_releases_pins(self):
        gpio = MagicMock()
        sensor = WaterLevel(gpio, 1, 6, 13, 8.62)
        with patch.object(sensor, "_distance_cm", side_effect=[3.0, None, 3.2, 3.1, None]), \
                patch("water_level.time.sleep"):
            fields = sensor.read()
            self.assertAlmostEqual(fields["distance_cm"], 3.1)
            self.assertAlmostEqual(fields["water_level_cm"], 5.52)
            self.assertAlmostEqual(fields["water_level_median_1m_cm"], 5.52)
        with patch.object(sensor, "_distance_cm", return_value=None), \
                patch("water_level.time.sleep"):
            self.assertIsNone(sensor.read())
        sensor.close()
        gpio.gpio_claim_output.assert_called_once_with(1, 6, 0)
        gpio.gpio_claim_input.assert_called_once_with(1, 13)
        gpio.gpio_free.assert_any_call(1, 13)
        gpio.gpio_free.assert_any_call(1, 6)

    def test_minute_median_uses_raw_echoes_in_the_last_60_seconds(self):
        sensor = WaterLevel(MagicMock(), 1, 6, 13, 8.62)
        with patch.object(sensor, "_distance_cm", side_effect=[3.0] * 5 + [5.0] * 5 + [7.0] * 5), \
                patch("water_level.time.sleep"), \
                patch("water_level.time.monotonic", side_effect=[0, 30, 61]):
            self.assertAlmostEqual(sensor.read()["water_level_median_1m_cm"], 5.62)
            self.assertAlmostEqual(sensor.read()["water_level_median_1m_cm"], 4.62)
            fields = sensor.read()
            self.assertAlmostEqual(fields["water_level_cm"], 1.62)
            self.assertAlmostEqual(fields["water_level_median_1m_cm"], 2.62)


if __name__ == "__main__":
    unittest.main()
