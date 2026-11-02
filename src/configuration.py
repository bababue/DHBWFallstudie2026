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
              'CO2_READY_POLL_SECONDS': (.2, 5), 'I2C_DELAY_US': (5, 1000), 'WATER_FILTER_SAMPLES': (3, 31), 'WATER_MAX_SPREAD_CM': (.01, 5)}
    for group, keys in expected.items():
        if not isinstance(data[group], dict) or set(data[group]) != keys:
            raise ValueError(f'{group}: unbekannte oder fehlende Einstellungen')
    for name, (group, key) in KEYS.items():
        value = data[group][key]
        if value is None and (name.endswith('EMPTY_DISTANCE_CM') or name == 'WATER_MAX_LEVEL_CM'):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{group}.{key}: gültige Zahl erforderlich')
        if 'GPIO' in name:
            if type(value) is not int or not 0 <= value <= 27:
                raise ValueError(f'{group}.{key}: GPIO muss eine ganze Zahl von 0 bis 27 sein')
            pins.append(value)
        elif name.endswith('ADDRESS'):
            if type(value) is not int or not 3 <= value <= 119:
                raise ValueError(f'{group}.{key}: I²C-Adresse muss 3 bis 119 sein')
        else:
            low, high = limits.get(name, (.001, 400))
            if not low <= value <= high:
                raise ValueError(f'{group}.{key}: erlaubter Bereich {low} bis {high}')
            if name == 'I2C_DELAY_US' and type(value) is not int:
                raise ValueError('i2c.taktpause_us: ganze Zahl erforderlich')
    count = data['wasserstand']['filter_messungen']
    if type(count) is not int or count % 2 == 0:
        raise ValueError('wasserstand.filter_messungen: ungerade ganze Zahl erforderlich')
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
