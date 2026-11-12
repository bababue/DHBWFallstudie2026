"""Daytime proportional cooling with an immediate, latched thermal cutoff."""
import math
from measurements import valid_number, fresh


def temperatures(readings, now):
    values = {}
    for r in readings:
        if (r.get('field') == 'temperature_c' and fresh(r.get('sampled'), now) and valid_number(r.get('value'))
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
        self.smoothed = None
        self.last_time = None
        self.outputs = {"fan": 0.0, "led": 0.0}

    def update(self, readings, options, schedule, now):
        target = options['temperatur_ziel_c']
        limit = options['temperatur_max_c']
        sides = temperatures(readings, now)
        available = [v for v in sides if v is not None]
        temp = max(available) if available else None
        missing = len(available) != 2
        dt = max(0, now - self.last_time) if self.last_time is not None else 0
        self.last_time = now
        tau = options.get('temperatur_glaettung_s', 10)
        if temp is not None:
            self.smoothed = temp if self.smoothed is None or tau == 0 else self.smoothed + (temp-self.smoothed)*(1-math.exp(-dt/tau))
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
            normal_temp = self.smoothed
            if normal_temp > target:
                self.cooling = True
            elif normal_temp < target - .3:
                self.cooling = False
            fan = max(5, min(100, (normal_temp-target)*100/(limit-target))) if self.cooling else 0
            factor = max(0, min(1, (limit-normal_temp)/(limit-target)))
            led = schedule['level'] * factor
            reason = 'Licht gedimmt · Kühlung' if self.cooling else 'Zielbereich'
        if missing or self.hot:
            self.outputs = dict(fan=float(fan), led=float(led))
        else:
            step = options.get('stellwert_aenderung_prozent_pro_s', 2) * dt
            for device, goal in (('fan', fan), ('led', led)):
                previous = self.outputs[device]
                self.outputs[device] = previous + max(-step, min(step, goal-previous))
            # Darkness and temperature dimming are upper limits, never delayed.
            self.outputs['led'] = min(self.outputs['led'], led)
            fan, led = self.outputs['fan'], self.outputs['led']
        fan = 0 if fan < 5 else round(fan)
        led = round(led)
        self.state = dict(temperature=temp, target=target, maximum=limit, fan=fan, led=led, reason=reason)
        return self.state
