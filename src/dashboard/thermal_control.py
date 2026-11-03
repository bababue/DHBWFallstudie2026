"""Daytime proportional cooling with an immediate, latched thermal cutoff."""
from pump_control import valid_number


def temperatures(readings, now):
    values = {}
    for r in readings:
        if (r.get('field') == 'temperature_c' and valid_number(r.get('sampled'))
                and 0 <= now - r['sampled'] <= 12 and valid_number(r.get('value'))
                and -40 <= r['value'] <= 125):
            values[(r.get('side'), r.get('sensor'))] = r['value']
    selected = [next((values[(side, sensor)] for sensor in ('sht45', 'scd40')
                      if (side, sensor) in values), None) for side in ('left', 'right')]
    return selected


class ThermalRegulator:
    def __init__(self):
        self.hot = False
        self.cooling = False
        self.state = None

    def update(self, readings, options, schedule, now):
        target = options['temperatur_ziel_c']
        limit = options['temperatur_max_c']
        sides = temperatures(readings, now)
        available = [v for v in sides if v is not None]
        temp = max(available) if available else None
        missing = len(available) != 2
        if temp is not None and temp >= limit:
            self.hot = True
        elif not missing and temp < limit - 1:
            self.hot = False
        if missing:
            fan, led, reason = 100, 0, 'Temperaturmessung fehlt · Licht aus'
        elif self.hot:
            fan, led, reason = 100, 0, 'Temperaturschutz · Licht aus'
        elif not schedule['active']:
            self.cooling = False
            fan, led, reason = 0, 0, 'Dunkelphase'
        else:
            if temp >= target + .3:
                self.cooling = True
            elif temp <= target:
                self.cooling = False
            # Quantized outputs and a dead band avoid rapid fan start/stop cycles.
            fan = max(5, min(100, round((temp-target)/(limit-target)*20)*5)) if self.cooling else 0
            dim_start = target + (limit-target)/3
            factor = max(0, min(1, (limit-temp)/(limit-dim_start)))
            led = round(schedule['level'] * factor / 5) * 5
            led = min(schedule['level'], led)
            reason = 'Licht gedimmt · Kühlung' if factor < 1 else ('Kühlung' if fan else 'Zielbereich' if temp >= target-.3 else 'Aufwärmen')
        self.state = dict(temperature=temp, target=target, maximum=limit, fan=fan, led=led, reason=reason)
        return self.state
