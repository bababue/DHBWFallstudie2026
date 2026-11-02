import unittest
from unittest.mock import MagicMock, patch

from water_level import WaterLevel


class WaterLevelTests(unittest.TestCase):
    def test_median_ignores_missing_echo_and_releases_pins(self):
        gpio = MagicMock()
        sensor = WaterLevel(gpio, 1, 6, 13, 8.62)
        with patch.object(sensor, "_distance_cm", side_effect=[3.0, None, 3.2, 3.1, None]), \
                patch("water_level.time.sleep"):
            self.assertAlmostEqual(sensor.read()["water_level_cm"], 5.52)
        with patch.object(sensor, "_distance_cm", return_value=None), \
                patch("water_level.time.sleep"):
            self.assertIsNone(sensor.read())
        sensor.close()
        gpio.gpio_claim_output.assert_called_once_with(1, 6, 0)
        gpio.gpio_claim_input.assert_called_once_with(1, 13)
        gpio.gpio_free.assert_any_call(1, 13)
        gpio.gpio_free.assert_any_call(1, 6)


if __name__ == "__main__":
    unittest.main()
