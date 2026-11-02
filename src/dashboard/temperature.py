"""Combine temperature measurements from the two sides of the box."""
from math import isfinite

PERIODS = {'10m': ('10m', '2s', 'last'), '1h': ('1h', '10s', 'last'), '24h': ('24h', '1m', 'mean'),
           '7d': ('7d', '5m', 'mean'), '30d': ('30d', '30m', 'mean')}


def combine(readings, unit="°"):
    selected = []
    for side in ('left', 'right'):
        for sensor in ({'ppm': ('scd40',), 'lx': ('bh1750',)}.get(unit, ('sht45', 'scd40'))):
            value = readings.get((side, sensor))
            if isinstance(value, (int, float)) and isfinite(value):
                selected.append((side, sensor, value))
                break
    if not selected:
        return {'value': None, 'source': 'Keine aktuellen Messwerte'}
    value = sum(item[2] for item in selected) / len(selected)
    by_side = {side: (sensor, reading) for side, sensor, reading in selected}
    lines = []
    for side, label in (('left', 'L'), ('right', 'R')):
        if side in by_side:
            sensor, reading = by_side[side]
            text = (f'{reading:.0f}' if unit in ('ppm', 'lx') else f'{reading:.1f}').replace('.', ',')
            lines.append(f"{label}: {text}{unit}{' (fallback)' if sensor == 'scd40' and unit != 'ppm' else ''}")
        else:
            lines.append(f'{label}: –')
    if len(selected) == 2:
        left = by_side['left'][1]
        if left == 0:
            lines.append('–')
        else:
            difference = (by_side['right'][1] - left) / left * 100
            lines.append(f'{difference:+.1f}%'.replace('.', ','))
    return {'value': value, 'source': '\n'.join(lines)}
