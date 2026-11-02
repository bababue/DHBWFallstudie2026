import time
import unittest
from unittest.mock import MagicMock, patch

from calibrate_co2 import calibrate_sensor, confirm_while_measuring, main, stable_readings
from sensors import crc8


def response(value):
    data = value.to_bytes(2, 'big')
    return data + bytes([crc8(data)])


class CalibrationTests(unittest.TestCase):
    def test_container_has_project_import_path_and_service_resumes_after_failure(self):
        with patch('sys.argv', ['calibrate_co2.py']), \
                patch('builtins.input', side_effect=['', 'j']), \
                patch('calibrate_co2.subprocess.check_output', return_value='sensors\n'), \
                patch('calibrate_co2.subprocess.run') as run:
            run.side_effect = [MagicMock(), MagicMock(returncode=1), MagicMock()]
            self.assertEqual(main(), 1)
        stop, invocation, restart = [call.args[0] for call in run.call_args_list]
        self.assertEqual(stop[-2:], ['stop', 'sensors'])
        self.assertIn('PYTHONPATH=/app', invocation)
        self.assertIn('/tmp/calibrate_co2.py', invocation)
        self.assertEqual(restart[-2:], ['start', 'sensors'])

    def test_measurement_continues_while_waiting_for_confirmation(self):
        measure = MagicMock()
        def delayed_input(_):
            time.sleep(0.05)
            return 'j'
        with patch('builtins.input', side_effect=delayed_input):
            self.assertTrue(confirm_while_measuring(430, measure, interval=0.005))
        self.assertGreater(measure.call_count, 0)

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
