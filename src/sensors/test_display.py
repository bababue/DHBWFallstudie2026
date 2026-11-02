"""Tests for the fixed sensor overview; no GPIO or display hardware required."""

import unittest

from oled import BREITE, HOEHE, Oled, overview_values, render, render_mode
from main import display_readings, should_store_sample, update_display_values


class OledTests(unittest.TestCase):
    def test_display_uses_recent_samples_and_expires_old_reads(self):
        values = {}
        update_display_values(values, "left", "sht45", {"temperature_c": 21.5}, 10)
        self.assertEqual(display_readings(values, 11)[("left", "sht45", "temperature_c")], 21.5)
        self.assertEqual(display_readings(values, 23), {})
        update_display_values(values, "left", "sht45", None, 24)
        self.assertEqual(values, {})

    def test_samples_are_only_stored_outside_maintenance(self):
        self.assertTrue(should_store_sample('AUTO', 'AUTO'))
        self.assertFalse(should_store_sample('AUTO', 'MAINTENANCE'))
        self.assertFalse(should_store_sample('MAINTENANCE', 'MAINTENANCE'))
        self.assertFalse(should_store_sample('MAINTENANCE', 'AUTO'))

    def test_overview_uses_scd40_as_temperature_backup(self):
        backup = {("left", "scd40", "temperature_c"): 21.5,
                  ("right", "scd40", "co2_ppm"): 530}
        primary = {("left", "sht45", "temperature_c"): 21.5,
                   ("right", "scd40", "co2_ppm"): 530}
        self.assertEqual(render(backup), render(primary))
        self.assertEqual(len(render(backup)), BREITE * HOEHE // 8)

    def test_overview_averages_dashboard_values_with_fallback(self):
        readings = {
            ("left", "sht45", "temperature_c"): 20,
            ("left", "scd40", "temperature_c"): 30,
            ("right", "scd40", "temperature_c"): 22,
            ("left", "sht45", "humidity_pct"): 70,
            ("right", "sht45", "humidity_pct"): 80,
            ("left", "scd40", "co2_ppm"): 400,
            ("right", "scd40", "co2_ppm"): 600,
            ("left", "bh1750", "illuminance_lux"): 12,
            ("right", "bh1750", "illuminance_lux"): 18,
            ("moss1", "ultrasonic", "height_cm"): 1,
            ("moss2", "ultrasonic", "height_cm"): 3,
        }
        self.assertEqual(overview_values(readings), {
            "moos": 2, "temperatur": 21, "luftfeuchtigkeit": 75,
            "co2": 500, "licht": 15,
        })
        self.assertEqual(overview_values({})['moos'], None)

    def test_display_keeps_recent_value_during_failed_read(self):
        values = {}
        update_display_values(values, "moss1", "ultrasonic", {"height_cm": 2}, 10)
        update_display_values(values, "moss1", "ultrasonic", None, 11)
        self.assertEqual(display_readings(values, 11)[("moss1", "ultrasonic", "height_cm")], 2)
        self.assertEqual(display_readings(values, 23), {})

    def test_each_mode_has_its_own_screen(self):
        frames = [render_mode(mode) for mode in ("AUTO", "MAINTENANCE", "MEASURING")]
        self.assertEqual(len(set(map(bytes, frames))), 3)
        self.assertTrue(all(len(frame) == BREITE * HOEHE // 8 for frame in frames))

    def test_oled_writes_the_overview_to_i2c(self):
        class Bus:
            def __init__(self):
                self.writes = []

            def write(self, address, payload):
                self.writes.append((address, payload))

        bus = Bus()
        oled = Oled(bus)
        oled.zeigen(render({("left", "sht45", "temperature_c"): 21.5}))
        self.assertTrue(bus.writes)
        self.assertTrue(all(address == 0x3C and isinstance(payload, bytes)
                            for address, payload in bus.writes))


if __name__ == "__main__":
    unittest.main()
