#!/usr/bin/env python3
"""Calibrate both SCD40 sensors in outdoor air at a user-confirmed reference."""
import argparse
import os
import statistics
import subprocess
import sys
import time
from threading import Event, Thread
from pathlib import Path

MEASUREMENT_SECONDS = 300
INTERVAL_SECONDS = 5
STABILITY_WINDOW_SECONDS = 75
MIN_RECENT_SAMPLES = 8
MAX_SPREAD_PPM = 100


def stable_readings(samples, now):
    recent = [value for timestamp, value in samples if 0 <= now - timestamp <= STABILITY_WINDOW_SECONDS]
    if len(recent) < MIN_RECENT_SAMPLES or max(recent) - min(recent) > MAX_SPREAD_PPM:
        return None
    return statistics.median(recent)


def confirm_while_measuring(reference_ppm, measure, interval=INTERVAL_SECONDS):
    """Keep sensor readings fresh while the user decides, without a timeout."""
    stop = Event()

    def loop():
        while not stop.wait(interval):
            measure()

    thread = Thread(target=loop, daemon=True)
    thread.start()
    try:
        return input(f'Sensoren auf {reference_ppm} ppm kalibrieren? [j/N] ').strip().lower() in ('j', 'ja', 'y', 'yes')
    finally:
        stop.set()
        thread.join()


def calibrate_sensor(sensor, reference_ppm, sleep=time.sleep):
    """SCD4x forced recalibration: stop, wait, send CRC-protected target, read correction."""
    from sensors import checked_word, crc8

    sensor.stop()
    sleep(0.5)
    target = reference_ppm.to_bytes(2, 'big')
    sensor.bus.write(sensor.address, b'\x36\x2f' + target + bytes([crc8(target)]))
    sleep(0.4)
    result = checked_word(sensor.bus.read(sensor.address, 3))
    if result == 0xffff:
        raise ValueError('Sensor meldet fehlgeschlagene Kalibrierung')
    return result - 0x8000


def measure_and_calibrate(reference_ppm):
    import lgpio
    import configuration
    from sensors import SCD40, SoftwareI2C

    config = configuration.load()
    pins = config['i2c']
    chip = os.getenv('GPIOCHIP_DEVICE', '/dev/gpiochip0')
    if not chip.startswith('/dev/gpiochip') or not chip[len('/dev/gpiochip'):].isdigit():
        raise ValueError('GPIOCHIP_DEVICE muss /dev/gpiochipN sein')
    handle = lgpio.gpiochip_open(int(chip[len('/dev/gpiochip'):]))
    buses, sensors, samples = [], {}, {}
    try:
        for side, sda, scl in (('Links', pins['links_sda_gpio'], pins['links_scl_gpio']),
                               ('Rechts', pins['rechts_sda_gpio'], pins['rechts_scl_gpio'])):
            try:
                bus = SoftwareI2C(lgpio, handle, sda, scl, pins['taktpause_us'])
                buses.append(bus)
                sensor = SCD40(bus, pins['scd40_adresse'])
                sensor.start()
                sensors[side] = sensor
                samples[side] = []
            except (OSError, ValueError, lgpio.error) as exc:
                print(f'{side}: Sensor konnte nicht gestartet werden: {exc}', flush=True)
        if not sensors:
            print('Kein CO₂-Sensor erreichbar.')
            return 1
        started = time.monotonic()
        print('Messung läuft fünf Minuten. Kasten geöffnet draußen stehen lassen, nicht auf die Sensoren atmen.', flush=True)
        def measure(verbose=True):
            for side, sensor in sensors.items():
                try:
                    reading = sensor.read()
                    if reading is not None:
                        value = reading['co2_ppm']
                        if 0 < value <= 40000:
                            now = time.monotonic()
                            samples[side].append((now, value))
                            samples[side][:] = [(at, val) for at, val in samples[side]
                                                if now - at <= STABILITY_WINDOW_SECONDS]
                            if verbose:
                                print(f'{side}: {value:.0f} ppm', flush=True)
                except (OSError, ValueError, lgpio.error) as exc:
                    if verbose:
                        print(f'{side}: Messung fehlgeschlagen: {exc}', flush=True)

        while time.monotonic() - started < MEASUREMENT_SECONDS:
            time.sleep(INTERVAL_SECONDS)
            measure()
        now = time.monotonic()
        for side in sensors:
            median = stable_readings(samples[side], now)
            if median is None:
                print(f'{side}: Zu wenige oder zu stark schwankende Messwerte.', flush=True)
            else:
                print(f'{side}: stabiler Median {median:.0f} ppm; Referenz {reference_ppm} ppm.', flush=True)
        try:
            confirmed = confirm_while_measuring(reference_ppm, lambda: measure(verbose=False))
        except (EOFError, KeyboardInterrupt):
            print('\nKalibrierung abgebrochen.')
            return 1
        if not confirmed:
            print('Kalibrierung abgebrochen.')
            return 0
        now = time.monotonic()
        eligible = [side for side in sensors if stable_readings(samples[side], now) is not None]
        for side in sensors:
            if side not in eligible:
                print(f'{side}: Zu wenige oder zu stark schwankende aktuelle Messwerte; keine Kalibrierung.', flush=True)
        if not eligible:
            return 1
        failed = False
        for side in eligible:
            try:
                correction = calibrate_sensor(sensors[side], reference_ppm)
                print(f'{side}: Kalibrierung erfolgreich, Korrektur {correction:+d} ppm.', flush=True)
            except (OSError, ValueError, lgpio.error) as exc:
                failed = True
                print(f'{side}: Kalibrierung fehlgeschlagen: {exc}', flush=True)
        return 1 if failed else 0
    finally:
        for sensor in sensors.values():
            try:
                sensor.stop()
            except Exception:
                pass
        for bus in reversed(buses):
            bus.close()
        lgpio.gpiochip_close(handle)


def main():
    parser = argparse.ArgumentParser(description='Beide SCD40-Sensoren in Außenluft kalibrieren.')
    parser.add_argument('--reference', type=int, help='Bekannte CO₂-Referenzkonzentration in ppm')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.reference is not None and not 400 <= args.reference <= 2000:
        parser.error('Referenz muss zwischen 400 und 2000 ppm liegen')
    if args.inside:
        if args.reference is None:
            parser.error('Referenz fehlt')
        return measure_and_calibrate(args.reference)
    try:
        print('Kasten geöffnet draußen aufstellen und für guten Luftaustausch sorgen.')
        print('430 ppm ist nur eine Schätzung; ein kalibriertes Referenzmessgerät ist genauer.')
        reference = args.reference
        if reference is None:
            value = input('Referenzwert in ppm [430]: ').strip()
            reference = int(value) if value else 430
        if not 400 <= reference <= 2000:
            print('Referenz muss zwischen 400 und 2000 ppm liegen.')
            return 1
        if input(f'Ist der Kasten geöffnet draußen und {reference} ppm die gewünschte Referenz? [j/N] ').strip().lower() not in ('j', 'ja', 'y', 'yes'):
            print('Kalibrierung abgebrochen.')
            return 0
        root = Path(__file__).resolve().parents[1]
        command = ['docker', 'compose']
        running = subprocess.check_output(command + ['ps', '--status', 'running', '--services'], cwd=root, text=True).splitlines()
        resume = 'sensors' in running
        try:
            if resume:
                subprocess.run(command + ['stop', 'sensors'], cwd=root, check=True)
            return subprocess.run(command + ['run', '--rm', '--no-deps', '-T', '--env', 'PYTHONPATH=/app', '--volume',
                                  f'{Path(__file__).resolve()}:/tmp/calibrate_co2.py:ro',
                                  'sensors', 'python', '-u', '/tmp/calibrate_co2.py',
                                  '--inside', '--reference', str(reference)], cwd=root).returncode
        finally:
            if resume:
                subprocess.run(command + ['start', 'sensors'], cwd=root, check=True)
    except (EOFError, KeyboardInterrupt):
        print('\nKalibrierung abgebrochen.')
        return 1
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'Kalibrierung nicht möglich: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
