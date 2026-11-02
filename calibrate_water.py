#!/usr/bin/env python3
"""Calibrate the water sensor at a known water depth using its raw echoes."""
import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Sensor-Boden-Abstand bei leerem Behälter bestimmen.')
    parser.add_argument('--write', action='store_true', help='Ergebnis in config/config.json speichern')
    parser.add_argument('--water-height', type=float, default=0, help='Bekannte Wassertiefe in cm (Standard: leer)')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.water_height < 0:
        parser.error('Wassertiefe darf nicht negativ sein')
    if not args.inside:
        root = Path(__file__).resolve().parent
        command = ['docker', 'compose']
        running = subprocess.check_output(command + ['ps', '--status', 'running', '--services'], cwd=root, text=True).splitlines()
        resume = 'sensors' in running
        try:
            if resume:
                subprocess.run(command + ['stop', 'sensors'], cwd=root, check=True)
            invocation = command + ['run', '--rm', '--no-deps', '-T', '-v', str(root / 'config') + ':/config',
                                    'sensors', 'python', '-', '--inside', '--water-height', str(args.water_height)]
            if args.write:
                invocation.append('--write')
            result = subprocess.run(invocation, cwd=root, input=Path(__file__).read_text(), text=True)
            return result.returncode
        finally:
            if resume:
                subprocess.run(command + ['start', 'sensors'], cwd=root, check=True)
    import lgpio
    import configuration
    from water_level import TimestampUltrasonic
    config = configuration.load()
    water = config['wasserstand']
    import os
    handle = lgpio.gpiochip_open(int(os.getenv('GPIOCHIP_DEVICE', '/dev/gpiochip0').removeprefix('/dev/gpiochip')))
    sensor = None
    samples = []
    try:
        sensor = TimestampUltrasonic(lgpio, handle, water['trigger_gpio'], water['echo_gpio'])
        print('Messung: ca. 10 Sekunden. Wasser ruhig halten, Messweg frei lassen.', flush=True)
        for _ in range(80):
            distance = sensor._distance_cm()
            if distance is not None and 0 < distance <= sensor.MAX_DISTANCE_CM:
                samples.append(distance)
            time.sleep(.1)
    finally:
        if sensor is not None:
            sensor.close()
        lgpio.gpiochip_close(handle)
    if len(samples) < 64:
        print('Zu wenige gültige Echos; keine Kalibrierung gespeichert.')
        return 1
    median = statistics.median(samples)
    inliers = [v for v in samples if abs(v - median) <= water['max_streuung_cm']]
    deviation = statistics.median(abs(v - median) for v in samples)
    print(f'Rohabstand Median: {median:.3f} cm; mediane Abweichung: {deviation:.3f} cm; gültig: {len(samples)}/80')
    if len(inliers) < .8 * len(samples):
        print('Messung zu instabil; Einbau prüfen. Keine Kalibrierung gespeichert.')
        return 1
    recommended = round(statistics.median(inliers) + args.water_height, 3)
    print(f'Sensor-Boden-Abstand: {recommended:.3f} cm')
    if args.write:
        water['sensor_boden_abstand_cm'] = recommended
        configuration.validate(config)
        path = configuration.PATH
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n')
        temporary.replace(path)
        print('config/config.json aktualisiert.')
    else:
        print('Nur Vorschlag. Mit --write speichern.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
