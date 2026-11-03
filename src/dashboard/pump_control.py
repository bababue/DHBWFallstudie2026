"""Fixed water target and continuous pump control."""
import math


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def target_level(config):
    maximum = config['wasserstand']['max_fuellhoehe_cm']
    if maximum is None:
        return None
    options = config['automatik']
    ceiling = maximum - config['wasserstand']['sicherheitsabstand_cm'] - options['pumpe_hysterese_cm']
    return max(0.0, min(options['wasser_ziel_cm'], ceiling))


def water_overview(readings, config, now):
    """The moss height remains a display value; the water target is fixed."""
    heights = []
    for reading in readings:
        if (reading.get('side') in ('moss1', 'moss2', 'moss3', 'moss4')
                and reading.get('sensor') == 'ultrasonic' and reading.get('field') == 'height_median_1m_cm'
                and valid_number(reading.get('sampled')) and 0 <= now - reading['sampled'] <= 12
                and valid_number(reading.get('value')) and reading['value'] >= 0):
            heights.append(reading['value'])
    return {'moss_height_cm': sum(heights) / len(heights) if heights else None,
            'target_cm': target_level(config)}


class PumpRegulator:
    """Run continuously up to the target; hysteresis prevents chatter afterward."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.reached = False
        self.reason = ''

    def value(self, data, options, now):
        valid = (data and data.get('water_ready') and data.get('pump_allowed')
                 and valid_number(data.get('target_cm'))
                 and valid_number(data.get('water_level_cm'))
                 and valid_number(data.get('raw_level_cm')))
        if not valid:
            self.reason = 'Warte auf sichere Messwerte'
            return 0
        target, level = data['target_cm'], data['water_level_cm']
        if target <= 0 or max(level, data['raw_level_cm']) >= target:
            self.reached = True
            self.reason = 'Zielwasserstand erreicht'
            return 0
        if self.reached and level >= target - options['pumpe_hysterese_cm']:
            self.reason = 'Zielwasserstand erreicht'
            return 0
        self.reached = False
        self.reason = 'Wasser wird nachgefüllt'
        return options['pumpe_leistung_prozent']
