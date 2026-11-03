#!/usr/bin/env python3
"""Check CRC-validated I2C sensor reads and average three raw echo samples."""

import argparse
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ECHO_SAMPLE_COUNT = 3
ECHO_SAMPLE_GAP_SECONDS = 0.1
MAX_ECHO_DISTANCE_CM = 400
I2C_SENSORS = (('SHT45', 'sht45_adresse'), ('BH1750', 'bh1750_adresse'),
               ('SCD40', 'scd40_adresse'))


def report_i2c_side(gpio, handle, config, side, pins, drivers, emit, sleep, monotonic):
    settings = config['i2c']
    try:
        bus = drivers['SoftwareI2C'](gpio, handle, pins[0], pins[1], settings['taktpause_us'])
    except Exception as exc:
        emit(f'{side}: I²C-Bus nicht verfügbar; SHT45, BH1750 und SCD40 nicht erreichbar ({exc})')
        return True

    failed = False
    try:
        for name, address_key in I2C_SENSORS:
            sensor = None
            try:
                sensor = drivers[name](bus, settings[address_key])
                if name == 'SCD40':
                    sensor.start()
                    deadline = monotonic() + 10
                    while True:
                        reading = sensor.read()
                        if reading is not None:
                            break
                        if monotonic() >= deadline:
                            raise TimeoutError('kein Messwert innerhalb von 10 s')
                        sleep(0.5)
                else:
                    reading = sensor.read()
                if name == 'BH1750':
                    emit(f'{side} {name}: Messwert {reading}; dieser Sensor bietet keine CRC-Prüfung')
                else:
                    emit(f'{side} {name}: CRC OK; Messwert {reading}')
            except Exception as exc:
                failed = True
                emit(f'{side} {name}: Prüfung fehlgeschlagen ({exc})')
            finally:
                if name == 'SCD40' and sensor is not None:
                    try:
                        sensor.stop()
                    except Exception as exc:
                        failed = True
                        emit(f'{side} SCD40: Stop fehlgeschlagen ({exc})')
    finally:
        try:
            bus.close()
        except Exception as exc:
            failed = True
            emit(f'{side}: I²C-Bus konnte nicht freigegeben werden ({exc})')
    return failed


def check_distance(gpio, handle, label, trigger, echo, pull_down, factory, emit, sleep):
    emit(f'{label}: Ultraschallsensor; keine CRC-Prüfung verfügbar')
    sensor = None
    failed = False
    samples = []
    raw_samples = []
    invalid = 0
    errors = 0
    try:
        sensor = factory(gpio, handle, trigger, echo, pull_down=pull_down)
        for index in range(ECHO_SAMPLE_COUNT):
            try:
                value = sensor._distance_cm()
                raw_samples.append(value)
                if (isinstance(value, (int, float)) and not isinstance(value, bool)
                        and math.isfinite(value) and 0 < value <= MAX_ECHO_DISTANCE_CM):
                    samples.append(float(value))
                else:
                    invalid += 1
            except Exception as exc:
                errors += 1
                raw_samples.append('Fehler')
                emit(f'{label}: Messung {index + 1}/{ECHO_SAMPLE_COUNT} fehlgeschlagen ({exc})')
            sleep(ECHO_SAMPLE_GAP_SECONDS)
    except Exception as exc:
        failed = True
        emit(f'{label}: Sensor konnte nicht gestartet werden ({exc})')
    finally:
        if sensor is not None:
            try:
                sensor.close()
            except Exception as exc:
                failed = True
                emit(f'{label}: Sensor konnte nicht freigegeben werden ({exc})')

    emit(f'{label}: Rohwerte {raw_samples}')
    if len(samples) == ECHO_SAMPLE_COUNT and errors == 0:
        emit(f'{label}: Mittelwert {sum(samples) / ECHO_SAMPLE_COUNT:.3f} cm (3/3 gültig)')
    else:
        failed = True
        emit(f'{label}: kein Mittelwert; {len(samples)}/3 gültig, {invalid} ungültig, {errors} Fehler')
    return failed


def run_diagnostic(config, gpio, drivers, chip, emit=print, sleep=time.sleep,
                   monotonic=time.monotonic):
    if not re.fullmatch(r'/dev/gpiochip\d+', chip):
        emit('GPIOCHIP_DEVICE muss /dev/gpiochipN sein')
        return 1
    try:
        handle = gpio.gpiochip_open(int(chip.removeprefix('/dev/gpiochip')))
    except Exception as exc:
        emit(f'GPIO-Chip konnte nicht geöffnet werden ({exc})')
        return 1

    failed = False
    try:
        i2c = config['i2c']
        for side, sda_key, scl_key in (
                ('Links', 'links_sda_gpio', 'links_scl_gpio'),
                ('Rechts', 'rechts_sda_gpio', 'rechts_scl_gpio')):
            failed |= report_i2c_side(gpio, handle, config, side,
                                      (i2c[sda_key], i2c[scl_key]), drivers, emit, sleep, monotonic)

        water = config['wasserstand']
        failed |= check_distance(gpio, handle, 'Wasser', water['trigger_gpio'], water['echo_gpio'],
                                 False, drivers['TimestampUltrasonic'], emit, sleep)
        for index in range(1, 5):
            moss = config['moos']['sensoren'][f'moos_{index}']
            failed |= check_distance(gpio, handle, f'Moos {index}', moss['trigger_gpio'], moss['echo_gpio'],
                                     True, drivers['TimestampUltrasonic'], emit, sleep)
    finally:
        try:
            gpio.gpiochip_close(handle)
        except Exception as exc:
            failed = True
            emit(f'GPIO-Chip konnte nicht geschlossen werden ({exc})')
    return 1 if failed else 0


def diagnostic_inside():
    import lgpio
    import configuration
    from sensors import BH1750, SCD40, SHT45, SoftwareI2C
    from water_level import TimestampUltrasonic

    drivers = {'SoftwareI2C': SoftwareI2C, 'SHT45': SHT45, 'BH1750': BH1750,
               'SCD40': SCD40, 'TimestampUltrasonic': TimestampUltrasonic}
    return run_diagnostic(configuration.load(), lgpio, drivers,
                          os.getenv('GPIOCHIP_DEVICE', '/dev/gpiochip0'))


def run_host(root, script_path, check_output=subprocess.check_output, run=subprocess.run):
    compose = ['docker', 'compose']
    try:
        running = set(check_output(compose + ['ps', '--status', 'running', '--services'],
                                   cwd=root, text=True).splitlines())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f'Docker-Compose-Status konnte nicht gelesen werden: {exc}', file=sys.stderr)
        return 1

    was_dashboard_running = 'dashboard' in running
    was_sensors_running = 'sensors' in running
    result = 1
    try:
        if was_dashboard_running:
            run(compose + ['stop', 'dashboard'], cwd=root, check=True)
        if was_sensors_running:
            run(compose + ['stop', 'sensors'], cwd=root, check=True)
        command = compose + ['run', '--rm', '--no-deps', '-T', '--env', 'PYTHONPATH=/app',
                             '--volume', f'{script_path}:/tmp/check_sensors.py:ro',
                             'sensors', 'python', '-u', '/tmp/check_sensors.py', '--inside']
        result = run(command, cwd=root).returncode
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f'Sensorprüfung konnte nicht gestartet werden: {exc}', file=sys.stderr)
        result = 1
    finally:
        if was_sensors_running:
            try:
                run(compose + ['start', 'sensors'], cwd=root, check=True)
            except (OSError, subprocess.CalledProcessError) as exc:
                print(f'Sensor-Dienst konnte nicht wieder gestartet werden: {exc}', file=sys.stderr)
                result = 1
        if was_dashboard_running:
            try:
                run(compose + ['start', 'dashboard'], cwd=root, check=True)
            except (OSError, subprocess.CalledProcessError) as exc:
                print(f'Dashboard konnte nicht wieder gestartet werden: {exc}', file=sys.stderr)
                result = 1
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Sensorprüfsummen und Abstandsmittelwerte prüfen.')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.inside:
        try:
            return diagnostic_inside()
        except KeyboardInterrupt:
            print('Sensorprüfung abgebrochen.', file=sys.stderr)
            return 1
        except Exception as exc:
            print(f'Sensorprüfung fehlgeschlagen: {exc}', file=sys.stderr)
            return 1
    root = Path(__file__).resolve().parents[1]
    try:
        return run_host(root, Path(__file__).resolve())
    except KeyboardInterrupt:
        print('Sensorprüfung abgebrochen.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
