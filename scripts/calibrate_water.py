#!/usr/bin/env python3
"""Calibrate the water sensor at a known water depth using raw echoes."""
import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SAMPLE_COUNT = 200
SAMPLE_INTERVAL_SECONDS = 0.1
MIN_VALID_FRACTION = 0.3
MIN_STABLE_FRACTION = 0.8
RESULT_PREFIX = 'WASSER_KALIBRIERUNG_JSON='


def main():
    parser = argparse.ArgumentParser(description='Sensor-Boden-Abstand bei bekanntem Wasserstand bestimmen.')
    parser.add_argument('--water-height', type=float, default=0, help='Bekannte Wassertiefe in cm (Standard: leer)')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not math.isfinite(args.water_height) or args.water_height < 0:
        parser.error('Wassertiefe muss eine gültige, nicht negative Zahl sein')
    if not args.inside:
        root = Path(__file__).resolve().parents[1]
        config_path = root / 'config' / 'config.json'
        original = config_path.read_bytes()
        revision = hashlib.sha256(original).digest()
        command = ['docker', 'compose']
        running = subprocess.check_output(command + ['ps', '--status', 'running', '--services'], cwd=root, text=True).splitlines()
        resume = 'sensors' in running
        try:
            if resume:
                subprocess.run(command + ['stop', 'sensors'], cwd=root, check=True)
            invocation = command + ['run', '--rm', '--no-deps', '-T', 'sensors', 'python', '-', '--inside',
                                    '--water-height', str(args.water_height)]
            with subprocess.Popen(invocation, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, bufsize=1) as process:
                process.stdin.write(Path(__file__).read_text())
                process.stdin.close()
                result = None
                for line in process.stdout:
                    if line.startswith(RESULT_PREFIX):
                        result = json.loads(line[len(RESULT_PREFIX):])
                    else:
                        print(line, end='', flush=True)
                code = process.wait()
            if code != 0 or result is None:
                return code or 1
            try:
                answer = input('Wert in config/config.json speichern? [j/N] ').strip().lower()
            except (EOFError, KeyboardInterrupt):
                print('\nNicht gespeichert.')
                return 1
            if answer not in ('j', 'ja', 'y', 'yes'):
                print('Nicht gespeichert.')
                return 0
            if hashlib.sha256(config_path.read_bytes()).digest() != revision:
                print('Konfiguration wurde zwischenzeitlich geändert; nichts gespeichert.')
                return 1
            sys.path.insert(0, str(root / 'src'))
            import configuration
            config = configuration.upgrade(json.loads(original))
            config['wasserstand']['sensor_boden_abstand_cm'] = result
            configuration.validate(config)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', dir=config_path.parent, delete=False) as output:
                    temporary = Path(output.name)
                    os.fchmod(output.fileno(), config_path.stat().st_mode & 0o777)
                    json.dump(config, output, indent=2, ensure_ascii=False)
                    output.write('\n')
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, config_path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            print('Sensor-Boden-Abstand in config/config.json gespeichert.')
            return 0
        finally:
            if resume:
                subprocess.run(command + ['start', 'sensors'], cwd=root, check=True)

    import lgpio
    import configuration
    from water_level import TimestampUltrasonic
    water = configuration.load()['wasserstand']
    handle = lgpio.gpiochip_open(int(os.getenv('GPIOCHIP_DEVICE', '/dev/gpiochip0').removeprefix('/dev/gpiochip')))
    sensor = None
    samples = []
    try:
        sensor = TimestampUltrasonic(lgpio, handle, water['trigger_gpio'], water['echo_gpio'])
        print(f'Messung: {SAMPLE_COUNT} Werte. Wasser ruhig halten, Messweg frei lassen.', flush=True)
        for _ in range(SAMPLE_COUNT):
            distance = sensor._distance_cm()
            if distance is not None and math.isfinite(distance) and 0 < distance <= sensor.MAX_DISTANCE_CM:
                samples.append(distance)
            time.sleep(SAMPLE_INTERVAL_SECONDS)
    finally:
        if sensor is not None:
            sensor.close()
        lgpio.gpiochip_close(handle)
    print(f'Gültige Echos: {len(samples)}/{SAMPLE_COUNT}', flush=True)
    if len(samples) < SAMPLE_COUNT * MIN_VALID_FRACTION:
        print('Zu wenige gültige Echos; keine Kalibrierung gespeichert.')
        return 1
    median = statistics.median(samples)
    inliers = [value for value in samples if abs(value - median) <= water['max_streuung_cm']]
    deviation = statistics.median(abs(value - median) for value in samples)
    print(f'Rohabstand Median: {median:.3f} cm; mediane Abweichung: {deviation:.3f} cm')
    if len(inliers) < MIN_STABLE_FRACTION * len(samples):
        print('Messung zu instabil; keine Kalibrierung gespeichert.')
        return 1
    recommended = round(statistics.median(inliers) + args.water_height, 3)
    print(f'Sensor-Boden-Abstand: {recommended:.3f} cm', flush=True)
    print(RESULT_PREFIX + json.dumps(recommended), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
