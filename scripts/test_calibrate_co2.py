import unittest
from unittest.mock import MagicMock

from calibrate_co2 import calibrate_sensor, stable_readings
from sensors import crc8


def response(value):
    data = value.to_bytes(2, 'big')
    return data + bytes([crc8(data)])


class CalibrationTests(unittest.TestCase):
    def test_stability_requires_enough_recent_values_without_large_jumps(self):
        self.assertIsNone(stable_readings([(0, 400)] * 7, 0))
        self.assertIsNone(stable_readings([(0, value) for value in [400] * 7 + [501]], 0))
        self.assertEqual(stable_readings([(0, value) for value in [400] * 7 + [420]], 0), 400)
        self.assertIsNone(stable_readings([(0, 400)] * 8, 76))

    def test_forced_calibration_sends_correct_command_and_decodes_correction(self):
        sensor = MagicMock()
        sensor.address = 0x62
        sensor.bus.read.return_value = response(0x8000 - 50)
        wait = MagicMock()
        self.assertEqual(calibrate_sensor(sensor, 430, wait), -50)
        sensor.stop.assert_called_once_with()
        target = (430).to_bytes(2, 'big')
        sensor.bus.write.assert_called_once_with(0x62, b'\x36\x2f' + target + bytes([crc8(target)]))
        self.assertEqual([call.args[0] for call in wait.call_args_list], [0.5, 0.4])

    def test_failure_and_crc_errors_are_reported(self):
        sensor = MagicMock()
        sensor.bus.read.return_value = response(0xffff)
        with self.assertRaises(ValueError):
            calibrate_sensor(sensor, 430, lambda _: None)
        sensor.bus.read.return_value = b'\x80\x00\x00'
        with self.assertRaises(ValueError):
            calibrate_sensor(sensor, 430, lambda _: None)


if __name__ == '__main__':
    unittest.main()
