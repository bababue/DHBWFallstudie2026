#!/usr/bin/env python3
"""Calibrate the four moss distance sensors against the paper reference."""
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
RESULT_PREFIX = "MOOS_KALIBRIERUNG_JSON="
MAX_DEVIATION_CM = 0.3
MIN_VALID_FRACTION = 0.3
MIN_STABLE_FRACTION = 0.8


def reference(samples):
    valid = [value for value in samples if value is not None and math.isfinite(value) and 0 < value <= 400]
    if len(valid) < SAMPLE_COUNT * MIN_VALID_FRACTION:
        return None
    center = statistics.median(valid)
    accepted = [value for value in valid if abs(value - center) <= MAX_DEVIATION_CM]
    if len(accepted) < len(valid) * MIN_STABLE_FRACTION:
        return None
    return round(statistics.median(accepted), 3)


def main():
    parser = argparse.ArgumentParser(description='Moossensoren mit Kalibrierungszettel auf Null setzen.')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.inside:
        try:
            input('Bitte leg den kalibrierungszettel auf die halterung.\nDrücke Enter, um zu starten. ')
        except (EOFError, KeyboardInterrupt):
            print('\nKalibrierung abgebrochen.')
            return 1
        root = Path(__file__).resolve().parents[1]
        command = ['docker', 'compose']
        config_path = root / 'config' / 'config.json'
        original = config_path.read_bytes()
        revision = hashlib.sha256(original).digest()
        running = subprocess.check_output(command + ['ps', '--status', 'running', '--services'], cwd=root, text=True).splitlines()
        resume = 'sensors' in running
        try:
            if resume:
                subprocess.run(command + ['stop', 'sensors'], cwd=root, check=True)
            invocation = command + ['run', '--rm', '--no-deps', '-T', 'sensors', 'python', '-', '--inside']
            with subprocess.Popen(invocation, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, bufsize=1) as process:
                process.stdin.write(Path(__file__).read_text())
                process.stdin.close()
                results = None
                for line in process.stdout:
                    if line.startswith(RESULT_PREFIX):
                        results = json.loads(line[len(RESULT_PREFIX):])
                    else:
                        print(line, end='', flush=True)
                code = process.wait()
            if code != 0 or not results:
                return code or 1
            try:
                answer = input('Werte in config/config.json speichern? [j/N] ').strip().lower()
            except (EOFError, KeyboardInterrupt):
                print('\nNicht gespeichert.')
                return 1
            if answer not in ('j', 'ja', 'y', 'yes'):
                print('Nicht gespeichert.')
                return 0
            if hashlib.sha256(config_path.read_bytes()).digest() != revision:
                print('Konfiguration wurde zwischenzeitlich geändert; keine Werte gespeichert.')
                return 1
            sys.path.insert(0, str(root / 'src'))
            import configuration
            config = configuration.upgrade(json.loads(original))
            for index, distance in results.items():
                config[f'moos_{index}']['bezugsabstand_cm'] = distance
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
            print('Bezugsabstände in config/config.json gespeichert.')
            return 0
        finally:
            if resume:
                subprocess.run(command + ['start', 'sensors'], cwd=root, check=True)

    import lgpio
    import configuration
    from moss_height import MossHeight
    config = configuration.load()
    chip = int(os.getenv('GPIOCHIP_DEVICE', '/dev/gpiochip0').removeprefix('/dev/gpiochip'))
    handle = lgpio.gpiochip_open(chip)
    results = {}
    try:
        for index in range(1, 5):
            settings = config[f'moos_{index}']
            sensor = None
            try:
                sensor = MossHeight(lgpio, handle, settings['trigger_gpio'], settings['echo_gpio'])
                samples = []
                print(f'Moos {index}: messe {SAMPLE_COUNT} Werte …', flush=True)
                for _ in range(SAMPLE_COUNT):
                    samples.append(sensor._distance_cm())
                    time.sleep(SAMPLE_INTERVAL_SECONDS)
                valid = [value for value in samples
                         if value is not None and math.isfinite(value) and 0 < value <= 400]
                print(f'Moos {index}: {len(valid)}/{SAMPLE_COUNT} gültige Echos', flush=True)
                result = reference(samples)
                if result is None:
                    reason = ('zu wenige gültige Echos' if len(valid) < SAMPLE_COUNT * MIN_VALID_FRACTION
                              else 'Messwerte streuen zu stark')
                    print(f'Moos {index}: {reason}; bisheriger Wert bleibt erhalten.', flush=True)
                else:
                    results[index] = result
                    print(f'Moos {index}: {result:.3f} cm', flush=True)
            except (OSError, ValueError, lgpio.error) as exc:
                print(f'Moos {index}: Messung fehlgeschlagen ({exc}); bisheriger Wert bleibt erhalten.', flush=True)
            finally:
                if sensor is not None:
                    sensor.close()
    finally:
        lgpio.gpiochip_close(handle)
    if not results:
        print('Kein Sensor konnte kalibriert werden.')
        return 1
    print(RESULT_PREFIX + json.dumps(results), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
