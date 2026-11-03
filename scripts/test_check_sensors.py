import subprocess
import unittest
from unittest.mock import MagicMock, call, patch

import check_sensors
from sensors import SCD40, SHT45, crc8


def config():
    return {
        'i2c': {'links_sda_gpio': 1, 'links_scl_gpio': 2,
                'rechts_sda_gpio': 3, 'rechts_scl_gpio': 4, 'taktpause_us': 5,
                'sht45_adresse': 68, 'bh1750_adresse': 35, 'scd40_adresse': 98},
        'wasserstand': {'trigger_gpio': 5, 'echo_gpio': 6},
        **{f'moos_{index}': {'trigger_gpio': 2 * index + 5,
                             'echo_gpio': 2 * index + 6, 'demo': True}
           for index in range(1, 5)},
    }


class DistanceTests(unittest.TestCase):
    def test_uses_three_raw_values_and_means_only_all_three(self):
        sensor = MagicMock()
        sensor._distance_cm.side_effect = [10, 11, 12]
        sleep = MagicMock()
        output = []
        failed = check_sensors.check_distance(
            None, 1, 'Wasser', 2, 3, False, lambda *args, **kwargs: sensor,
            output.append, sleep)
        self.assertFalse(failed)
        self.assertEqual(sensor._distance_cm.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(0.1)] * 3)
        self.assertTrue(any('Rohwerte [10, 11, 12]' in line for line in output))
        self.assertTrue(any('Mittelwert 11.000 cm (3/3 gültig)' in line for line in output))
        self.assertTrue(any('keine CRC-Prüfung verfügbar' in line for line in output))
        sensor.close.assert_called_once_with()


class CrcDriverTests(unittest.TestCase):
    def test_existing_drivers_reject_corrupt_sensor_words(self):
        class Bus:
            def write(self, address, payload):
                pass

            def read(self, address, count):
                if count == 6:
                    return b'\x12\x34\x00\x56\x78\x00'
                if count == 3:
                    word = b'\x00\x01'
                    return word + bytes([crc8(word)])
                if count == 9:
                    return b'\x00' * 9
                raise AssertionError(count)

        with patch('sensors.time.sleep', lambda _: None):
            with self.assertRaisesRegex(ValueError, 'CRC'):
                SHT45(Bus(), 0x44).read()
            sensor = SCD40(Bus(), 0x62)
            sensor.start()
            with self.assertRaisesRegex(ValueError, 'CRC'):
                sensor.read()


class DiagnosticFlowTests(unittest.TestCase):
    def test_crc_error_is_reported_and_remaining_sensors_are_still_checked(self):
        class Bus:
            def close(self):
                pass

        class I2CSensor:
            def __init__(self, bus, address):
                self.address = address

            def read(self):
                if self.address == 68:
                    raise ValueError('Sensor CRC error')
                return {'measurement': 1}

            def start(self):
                pass

            def stop(self):
                pass

        class EchoSensor:
            def __init__(self, *args, **kwargs):
                self.values = iter((1, 2, 3))

            def _distance_cm(self):
                return next(self.values)

            def close(self):
                pass

        gpio = MagicMock()
        gpio.gpiochip_open.return_value = 1
        drivers = {'SoftwareI2C': lambda *args: Bus(), 'SHT45': I2CSensor,
                   'BH1750': I2CSensor, 'SCD40': I2CSensor,
                   'TimestampUltrasonic': EchoSensor}
        output = []
        result = check_sensors.run_diagnostic(
            config(), gpio, drivers, '/dev/gpiochip0', output.append,
            lambda _: None, lambda: 0)
        self.assertEqual(result, 1)
        self.assertTrue(any('Links SHT45: Prüfung fehlgeschlagen' in line for line in output))
        self.assertTrue(any('Links BH1750: Messwert' in line for line in output))
        self.assertTrue(any('Rechts SCD40: CRC OK' in line for line in output))
        self.assertEqual(sum('Mittelwert' in line for line in output), 5)
        self.assertEqual(gpio.gpiochip_close.call_count, 1)

    def test_scd40_timeout_stops_sensor_and_releases_bus(self):
        class Bus:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        class Sensor:
            def __init__(self, *args):
                self.stopped = False

            def start(self):
                pass

            def read(self):
                return None

            def stop(self):
                self.stopped = True

        bus = Bus()
        sensors = []

        def sensor_factory(*args):
            sensor = Sensor()
            sensors.append(sensor)
            return sensor

        drivers = {'SoftwareI2C': lambda *args: bus,
                   'SHT45': sensor_factory, 'BH1750': sensor_factory,
                   'SCD40': sensor_factory}
        output = []
        times = iter((0, 11))
        failed = check_sensors.report_i2c_side(
            None, 1, config(), 'Links', (1, 2), drivers, output.append,
            lambda _: None, lambda: next(times))
        self.assertTrue(failed)
        self.assertTrue(sensors[-1].stopped)
        self.assertTrue(bus.closed)
        self.assertTrue(any('10 s' in line for line in output))

    def test_invalid_and_raising_samples_still_attempt_all_three_and_have_no_mean(self):
        sensor = MagicMock()
        sensor._distance_cm.side_effect = [8, RuntimeError('no echo'), float('inf')]
        output = []
        failed = check_sensors.check_distance(
            None, 1, 'Moos 1', 2, 3, True, lambda *args, **kwargs: sensor,
            output.append, lambda _: None)
        self.assertTrue(failed)
        self.assertEqual(sensor._distance_cm.call_count, 3)
        self.assertTrue(any('kein Mittelwert; 1/3 gültig, 1 ungültig, 1 Fehler' in line
                            for line in output))
        self.assertFalse(any('Mittelwert ' in line for line in output))
        sensor.close.assert_called_once_with()


class HostWrapperTests(unittest.TestCase):
    def test_restores_original_services_in_order_after_diagnostic_failure(self):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            if 'python' in command:
                return subprocess.CompletedProcess(command, 1)
            return subprocess.CompletedProcess(command, 0)

        status = lambda *args, **kwargs: 'sensors\ndashboard\n'
        result = check_sensors.run_host('/repo', '/repo/scripts/check_sensors.py', status, run)
        self.assertEqual(result, 1)
        self.assertEqual([command[2:4] for command in calls], [
            ['stop', 'dashboard'], ['stop', 'sensors'],
            ['run', '--rm'], ['start', 'sensors'], ['start', 'dashboard']])
        self.assertIn('--no-deps', calls[2])
        self.assertIn('-T', calls[2])
        self.assertIn('PYTHONPATH=/app', calls[2])

    def test_does_not_start_services_that_were_stopped(self):
        calls = []
        run = lambda command, **kwargs: calls.append(command) or subprocess.CompletedProcess(command, 0)
        result = check_sensors.run_host('/repo', '/repo/scripts/check_sensors.py',
                                        lambda *args, **kwargs: '', run)
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2:4], ['run', '--rm'])


if __name__ == '__main__':
    unittest.main()
