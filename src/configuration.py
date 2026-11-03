"""Shared, validated configuration; credentials remain in the environment."""
import hashlib
import json
import math
import os
from pathlib import Path

PATH = Path('/config/config.json') if Path('/config').exists() else Path(__file__).resolve().parents[1] / 'config/config.json'
KEYS = json.loads(Path(__file__).with_name('config_keys.json').read_text())


def validate(data):
    expected = {}
    for group, key in KEYS.values():
        expected.setdefault(group, set()).add(key)
    if not isinstance(data, dict) or set(data) != set(expected):
        raise ValueError('Die Konfigurationsbereiche müssen vollständig erhalten bleiben.')
    pins = []
    limits = {'FAST_SAMPLE_INTERVAL_SECONDS': (.5, 60), 'MOSS_SAMPLE_INTERVAL_SECONDS': (4, 60),
              'CO2_READY_POLL_SECONDS': (.2, 5), 'I2C_DELAY_US': (5, 1000),
              'AUTO_TEMPERATURE_TARGET_C': (5, 30), 'AUTO_TEMPERATURE_MAX_C': (7, 35), 'WATER_BELOW_MOSS_CM': (0, 400), 'PUMP_HYSTERESIS_CM': (.05, 2)}
    for group, keys in expected.items():
        if not isinstance(data[group], dict) or set(data[group]) != keys:
            raise ValueError(f'{group}: unbekannte oder fehlende Einstellungen')
    for name, (group, key) in KEYS.items():
        value = data[group][key]
        if value is None and name.endswith('MOUNT_HEIGHT_CM'):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{group}.{key}: gültige Zahl erforderlich')
        if 'GPIO' in name:
            if type(value) is not int or not 0 <= value <= 27:
                raise ValueError(f'{group}.{key}: GPIO muss eine ganze Zahl von 0 bis 27 sein')
            pins.append(value)
        elif name in ('AUTO_LIGHT_START_HOUR', 'AUTO_LIGHT_DURATION_HOURS', 'AUTO_LIGHT_LEVEL_PERCENT'):
            low, high = {'AUTO_LIGHT_START_HOUR': (0, 23), 'AUTO_LIGHT_DURATION_HOURS': (1, 23),
                         'AUTO_LIGHT_LEVEL_PERCENT': (0, 100)}[name]
            if type(value) is not int or not low <= value <= high or (name == 'AUTO_LIGHT_LEVEL_PERCENT' and 0 < value < 5):
                raise ValueError(f'{group}.{key}: erlaubte ganze Zahl {low} bis {high}')
        elif name == 'PUMP_LEVEL_PERCENT':
            if type(value) is not int or not 5 <= value <= 100:
                raise ValueError('automatik.pumpe_leistung_prozent: ganze Zahl 5 bis 100 erforderlich')
        elif name.endswith('_PWM_HZ'):
            if type(value) is not int or not 1 <= value <= 20000:
                raise ValueError(f'{group}.{key}: PWM-Frequenz muss eine ganze Zahl von 1 bis 20000 sein')
        elif name.endswith('ADDRESS'):
            if type(value) is not int or not 3 <= value <= 119:
                raise ValueError(f'{group}.{key}: I²C-Adresse muss 3 bis 119 sein')
        else:
            low, high = limits.get(name, (.001, 400))
            if not low <= value <= high:
                raise ValueError(f'{group}.{key}: erlaubter Bereich {low} bis {high}')
            if name == 'I2C_DELAY_US' and type(value) is not int:
                raise ValueError('i2c.taktpause_us: ganze Zahl erforderlich')
    if data['automatik']['temperatur_max_c'] - data['automatik']['temperatur_ziel_c'] < 2:
        raise ValueError('Temperaturmaximum muss mindestens 2 °C über dem Ziel liegen')
    maximum = data['wasserstand']['max_fuellhoehe_cm']
    if maximum is not None and maximum >= data['wasserstand']['sensor_boden_abstand_cm']:
        raise ValueError('Maximale Füllhöhe muss kleiner als der Sensor-Boden-Abstand sein')
    if len(pins) != len(set(pins)):
        raise ValueError('Jeder GPIO darf nur einmal vergeben sein.')
    return data


def load():
    return validate(json.loads(PATH.read_text()))


def setting(name, default=None):
    if name not in KEYS:
        return os.getenv(name, default)
    group, key = KEYS[name]
    value = load()[group][key]
    return '' if value is None else str(value)


def revision():
    return hashlib.sha256(PATH.read_bytes()).hexdigest()
