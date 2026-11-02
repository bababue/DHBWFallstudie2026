import unittest
import os
from unittest.mock import patch

from main import Config
from sensors import BH1750, SCD40, SHT45, checked_word, crc8


def word(value):
    data = value.to_bytes(2, "big")
    return data + bytes([crc8(data)])


class FakeBus:
    def __init__(self, responses):
        self.responses = list(responses)
        self.writes = []

    def write(self, address, payload):
        self.writes.append((address, payload))

    def read(self, address, count):
        response = self.responses.pop(0)
        assert len(response) == count
        return response


class SensorTests(unittest.TestCase):
    def setUp(self):
        getter = patch("main.setting", side_effect=lambda name, default=None: os.getenv(name, default))
        getter.start()
        self.addCleanup(getter.stop)

    def test_water_sensor_pins_and_floor_distance(self):
        with patch.dict(os.environ, {"INFLUXDB_TOKEN": "test"}, clear=True):
            config = Config.from_config()
            self.assertEqual((config.water_trigger, config.water_echo), (6, 13))
            self.assertEqual(config.water_floor_distance_cm, 8.62)
            self.assertEqual(config.button_pin, 26)
            os.environ["WATER_ECHO_GPIO"] = "14"
            with self.assertRaises(ValueError):
                Config.from_config()
            os.environ["WATER_ECHO_GPIO"] = "13"
            os.environ["BUTTON_GPIO"] = "13"
            with self.assertRaises(ValueError):
                Config.from_config()

    def test_two_moss_sensor_pins_and_optional_references(self):
        with patch.dict(os.environ, {"INFLUXDB_TOKEN": "test"}, clear=True):
            config = Config.from_config()
            self.assertEqual(config.moss_pins, ((9, 11), (0, 5)))
            self.assertEqual(config.moss_empty_distances_cm, (None,) * 2)
            os.environ["MOSS_1_EMPTY_DISTANCE_CM"] = "20.5"
            self.assertEqual(Config.from_config().moss_empty_distances_cm[0], 20.5)
            os.environ["MOSS_2_ECHO_GPIO"] = "13"
            with self.assertRaises(ValueError):
                Config.from_config()

    def test_independent_fast_and_co2_poll_intervals(self):
        with patch.dict(os.environ, {"INFLUXDB_TOKEN": "test"}, clear=True):
            self.assertEqual(Config.from_config().fast_interval, 1)
            self.assertEqual(Config.from_config().co2_poll_interval, 0.5)
            os.environ["FAST_SAMPLE_INTERVAL_SECONDS"] = "0.1"
            with self.assertRaises(ValueError):
                Config.from_config()
            os.environ["FAST_SAMPLE_INTERVAL_SECONDS"] = "1"
            os.environ["CO2_READY_POLL_SECONDS"] = "0.1"
            with self.assertRaises(ValueError):
                Config.from_config()

    def test_crc_rejects_corruption(self):
        self.assertEqual(crc8(b"\xbe\xef"), 0x92)
        with self.assertRaises(ValueError):
            checked_word(b"\xbe\xef\x00")

    def test_sht45_converts_two_words(self):
        bus = FakeBus([word(0x8000) + word(0x8000)])
        values = SHT45(bus, 0x44).read()
        self.assertAlmostEqual(values["temperature_c"], 42.5013, places=3)
        self.assertAlmostEqual(values["humidity_pct"], 56.50095, places=3)
        self.assertEqual(bus.writes, [(0x44, b"\xfd")])

    def test_bh1750_uses_power_and_one_shot_mode(self):
        bus = FakeBus([b"\x00\x78"])
        self.assertAlmostEqual(BH1750(bus, 0x23).read()["illuminance_lux"], 100)
        self.assertEqual(bus.writes, [(0x23, b"\x01"), (0x23, b"\x20")])

    def test_scd40_reads_all_three_values(self):
        bus = FakeBus([word(1), word(500) + word(0x6667) + word(0x5EB9)])
        values = SCD40(bus, 0x62).read()
        self.assertEqual(values["co2_ppm"], 500)
        self.assertAlmostEqual(values["temperature_c"], 25, places=2)
        self.assertAlmostEqual(values["humidity_pct"], 37, places=2)
        self.assertEqual(bus.writes, [(0x62, b"\xe4\xb8"), (0x62, b"\xec\x05")])

    def test_scd40_not_ready_has_no_stale_sample(self):
        bus = FakeBus([word(0)])
        self.assertIsNone(SCD40(bus, 0x62).read())
        self.assertEqual(bus.writes, [(0x62, b"\xe4\xb8")])


if __name__ == "__main__":
    unittest.main()
