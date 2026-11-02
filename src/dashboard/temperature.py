"""Combine temperature measurements from the two sides of the box."""
from math import isfinite

PERIODS = {'1h': ('1h', '10s', 'last'), '24h': ('24h', '1m', 'mean'),
           '7d': ('7d', '5m', 'mean'), '30d': ('30d', '30m', 'mean')}


def combine(readings):
    selected = []
    for side in ('left', 'right'):
        for sensor in ('sht45', 'scd40'):
            value = readings.get((side, sensor))
            if isinstance(value, (int, float)) and isfinite(value):
                selected.append((side, sensor, value))
                break
    if not selected:
        return {'value': None, 'source': 'Keine aktuellen Messwerte'}
    value = sum(item[2] for item in selected) / len(selected)
    labels = [f"{'links' if side == 'left' else 'rechts'}: {sensor.upper()}"
              f"{' (Backup)' if sensor == 'scd40' else ''}" for side, sensor, _ in selected]
    source = ('Nur ' if len(selected) == 1 else '') + ', '.join(labels)
    if len(selected) == 2 and abs(selected[0][2] - selected[1][2]) >= 2:
        source += f" · Unterschied: {abs(selected[0][2] - selected[1][2]):.1f} °C"
    return {'value': value, 'source': source}
