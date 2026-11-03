"""Water target from moss tips and bounded pump pulses."""
import math


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def target_from_height(height, config):
    maximum = config['wasserstand']['max_fuellhoehe_cm']
    if not valid_number(height) or maximum is None:
        return None
    options = config['automatik']
    ceiling = maximum - config['wasserstand']['sicherheitsabstand_cm'] - options['pumpe_hysterese_cm']
    return max(0.0, min(height - options['wasser_unter_moosspitzen_cm'], ceiling))


def moss_target(readings, config, now):
    """Use recent one-minute medians, including explicitly enabled demo sensors."""
    by_sensor = {}
    for reading in readings:
        if (reading.get('side') in ('moss1', 'moss2', 'moss3', 'moss4')
                and reading.get('sensor') == 'ultrasonic'
                and valid_number(reading.get('sampled')) and 0 <= now - reading['sampled'] <= 12):
            by_sensor.setdefault(reading['side'], {})[reading['field']] = reading['value']
    heights, stable = [], []
    for fields in by_sensor.values():
        height = fields.get('height_median_1m_cm')
        if valid_number(height) and height >= 0:
            heights.append(height)
            if fields.get('measurement_stable') == 1:
                stable.append(height)
    height = sum(heights) / len(heights) if heights else None
    # At least two stable measurement positions are required to drive the pump.
    ready = len(stable) >= 2 and len(stable) == len(heights)
    return {'moss_height_cm': height, 'target_cm': target_from_height(height, config),
            'moss_ready': ready}


class PumpRegulator:
    """One-second pulses with settling pauses, hysteresis and a refill time budget."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.refilling = False
        self.pulse_started = None
        self.next_pulse = 0.0
        self.total_runtime = 0.0
        self.fault = False
        self.reason = ''

    def _stop(self, now, options):
        if self.pulse_started is not None:
            self.total_runtime += max(0.0, now - self.pulse_started)
            self.pulse_started = None
            self.next_pulse = now + options['pumpe_pause_s']

    def value(self, data, options, now):
        if self.fault:
            self.reason = 'Pumpenlaufzeit erreicht · MANUAL → AUTO zum Zurücksetzen'
            return 0
        valid = (data and data.get('moss_ready') and data.get('water_ready')
                 and data.get('pump_allowed')
                 and valid_number(data.get('target_cm'))
                 and valid_number(data.get('water_level_cm'))
                 and valid_number(data.get('raw_level_cm')))
        if not valid:
            self._stop(now, options)
            self.reason = 'Warte auf sichere Messwerte'
            return 0
        target, level = data['target_cm'], data['water_level_cm']
        if target <= 0 or max(level, data['raw_level_cm']) >= target:
            self._stop(now, options)
            self.refilling = False
            self.total_runtime = 0
            self.reason = 'Zielwasserstand erreicht'
            return 0
        if self.pulse_started is not None:
            elapsed = now - self.pulse_started
            if self.total_runtime + elapsed >= options['pumpe_max_laufzeit_s']:
                self._stop(now, options)
                self.fault = True
                self.reason = 'Pumpenlaufzeit erreicht · MANUAL → AUTO zum Zurücksetzen'
                return 0
            if elapsed < options['pumpe_impuls_s']:
                self.reason = 'Wasser wird nachgefüllt'
                return options['pumpe_leistung_prozent']
            self._stop(now, options)
        if not self.refilling:
            if level >= target - options['pumpe_hysterese_cm']:
                self.reason = 'Zielwasserstand erreicht'
                return 0
            self.refilling = True
        if self.total_runtime >= options['pumpe_max_laufzeit_s']:
            self.fault = True
            self.reason = 'Pumpenlaufzeit erreicht · MANUAL → AUTO zum Zurücksetzen'
            return 0
        if now < self.next_pulse:
            self.reason = 'Wasser beruhigt sich'
            return 0
        self.pulse_started = now
        self.reason = 'Wasser wird nachgefüllt'
        return options['pumpe_leistung_prozent']
