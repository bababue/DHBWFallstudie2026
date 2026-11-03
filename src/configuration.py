"""Shared, validated configuration; credentials remain in the environment."""
import hashlib
import json
import math
import os
from pathlib import Path

PATH = Path('/config/config.json') if Path('/config').exists() else Path(__file__).resolve().parents[1] / 'config/config.json'
KEYS = json.loads(Path(__file__).with_name('config_keys.json').read_text())


def upgrade(data):
    if isinstance(data, dict):
        data = dict(data)
        data.setdefault("moos_3", {"trigger_gpio": 22, "echo_gpio": 10, "bezugsabstand_cm": None})
        data.setdefault("moos_4", {"trigger_gpio": 17, "echo_gpio": 27, "bezugsabstand_cm": None})
        data.pop("deckel", None)
        data.setdefault("automatik", {"licht_start_stunde": 6, "lichtdauer_stunden": 16,
                                      "lichtstaerke_prozent": 50})
        if isinstance(data.get("automatik"), dict):
            options = dict(data["automatik"])
            legacy_pulse = 'pumpe_impuls_s' in options
            for key in ('wasser_ziel_cm', 'pumpe_impuls_s', 'pumpe_pause_s', 'pumpe_max_laufzeit_s'):
                options.pop(key, None)
            options.setdefault('temperatur_ziel_c', 22)
            options.setdefault('temperatur_max_c', 25)
            options.setdefault('wasser_unter_moosspitzen_cm', 2)
            options.setdefault('pumpe_hysterese_cm', 0.2)
            options.setdefault('pumpe_start_stunde', 6)
            options.setdefault('pumpe_start_minute', 0)
            # Replace the previous pulse default when upgrading to continuous operation.
            if legacy_pulse and options.get('pumpe_leistung_prozent') == 30:
                options['pumpe_leistung_prozent'] = 25
            options.setdefault('pumpe_leistung_prozent', 25)
            data["automatik"] = options
        data.setdefault("aktoren", {"licht_gpio": 20, "luefter_gpio": 21, "pumpe_gpio": 16,
                                    "licht_pwm_hz": 2000, "luefter_pwm_hz": 5, "pumpe_pwm_hz": 5})
        if isinstance(data.get("wasserstand"), dict):
            water = dict(data["wasserstand"])
            water.setdefault("sicherheitsabstand_cm", 1.0)
            data["wasserstand"] = water
        legacy_demo = data.pop("moos_demo", None)
        for index in range(1, 5):
            key = f"moos_{index}"
            if isinstance(data.get(key), dict):
                sensor = dict(data[key])
                legacy_enabled = isinstance(legacy_demo, dict) and legacy_demo.get("demo_data") is True
                sensor.setdefault("demo", legacy_enabled)
                reference = sensor.get("bezugsabstand_cm")
                default_distance = (round(reference + 1, 3)
                                    if isinstance(reference, (int, float)) and not isinstance(reference, bool)
                                    and math.isfinite(reference) and 0 < reference <= 399 else None)
                sensor.setdefault("demo_abstand_cm", default_distance)
                data[key] = sensor
    return data


def validate(data):
    expected = {}
    for group, key in KEYS.values():
        expected.setdefault(group, set()).add(key)
    if not isinstance(data, dict) or set(data) != set(expected):
        raise ValueError('Die Konfigurationsbereiche müssen vollständig erhalten bleiben.')
    pins = []
    limits = {'FAST_SAMPLE_INTERVAL_SECONDS': (.5, 60), 'MOSS_SAMPLE_INTERVAL_SECONDS': (4, 60),
              'CO2_READY_POLL_SECONDS': (.2, 5), 'I2C_DELAY_US': (5, 1000), 'WATER_FILTER_SAMPLES': (3, 31), 'WATER_MAX_SPREAD_CM': (.01, 5),
              'AUTO_TEMPERATURE_TARGET_C': (5, 30), 'AUTO_TEMPERATURE_MAX_C': (7, 35), 'WATER_BELOW_MOSS_CM': (0, 400), 'PUMP_HYSTERESIS_CM': (.05, 2)}
    for group, keys in expected.items():
        if not isinstance(data[group], dict) or set(data[group]) != keys:
            raise ValueError(f'{group}: unbekannte oder fehlende Einstellungen')
    for name, (group, key) in KEYS.items():
        value = data[group][key]
        if value is None and (name.endswith('EMPTY_DISTANCE_CM') or name.endswith('DEMO_DISTANCE_CM') or name == 'WATER_MAX_LEVEL_CM'):
            continue
        if name.startswith('MOSS_') and name.endswith('_DEMO'):
            if type(value) is not bool:
                raise ValueError(f'{group}.{key}: true oder false erforderlich')
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
        elif name in ('PUMP_START_HOUR', 'PUMP_START_MINUTE'):
            high = 23 if name == 'PUMP_START_HOUR' else 59
            if type(value) is not int or not 0 <= value <= high:
                raise ValueError(f'{group}.{key}: ganze Zahl von 0 bis {high} erforderlich')
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
    count = data['wasserstand']['filter_messungen']
    if type(count) is not int or count % 2 == 0:
        raise ValueError('wasserstand.filter_messungen: ungerade ganze Zahl erforderlich')
    maximum = data['wasserstand']['max_fuellhoehe_cm']
    if maximum is not None and data['wasserstand']['sicherheitsabstand_cm'] >= maximum:
        raise ValueError('Sicherheitsabstand muss kleiner als die maximale Füllhöhe sein')
    if maximum is not None and maximum >= data['wasserstand']['sensor_boden_abstand_cm']:
        raise ValueError('Maximale Füllhöhe muss kleiner als der Sensor-Boden-Abstand sein')
    if len(pins) != len(set(pins)):
        raise ValueError('Jeder GPIO darf nur einmal vergeben sein.')
    return data


def load():
    return validate(upgrade(json.loads(PATH.read_text())))


def setting(name, default=None):
    if name not in KEYS:
        return os.getenv(name, default)
    group, key = KEYS[name]
    value = load()[group][key]
    return '' if value is None else str(value)


def revision():
    return hashlib.sha256(PATH.read_bytes()).hexdigest()
