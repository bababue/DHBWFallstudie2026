"""Tests for the fixed sensor overview; no GPIO or display hardware required."""

import unittest

from oled import BREITE, HOEHE, Oled, render


class OledTests(unittest.TestCase):
    def test_overview_uses_scd40_as_temperature_backup(self):
        backup = {("left", "scd40", "temperature_c"): 21.5,
                  ("right", "scd40", "co2_ppm"): 530}
        primary = {("left", "sht45", "temperature_c"): 21.5,
                   ("right", "scd40", "co2_ppm"): 530}
        self.assertEqual(render(backup), render(primary))
        self.assertEqual(len(render(backup)), BREITE * HOEHE // 8)

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
