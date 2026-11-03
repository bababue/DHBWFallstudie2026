"""One moss-derived target and a small pump state machine."""
from measurements import valid_number, fresh, PUMP_START_CONFIRM_SECONDS, MAX_DISTANCE_CM


def water_overview(readings, config, now):
    values = {(r.get('side'), r.get('field')): r for r in readings
              if r.get('sensor') == 'ultrasonic' and fresh(r.get('sampled'), now)}
    distances = {}
    heights = []
    expected = 0
    for index in range(1, 5):
        side = f'moss{index}'
        distance = values.get((side, 'distance_filtered_cm'), {})
        stable = values.get((side, 'measurement_stable'), {})
        value = distance.get('value')
        valid = (valid_number(value) and 0 < value <= MAX_DISTANCE_CM and stable.get('value') == 1
                 and distance.get('sampled') == stable.get('sampled'))
        distances[side] = value if valid else None
        mount = config['moos']['montagehoehe_cm']
        if mount is not None:
            expected += 1
            if valid and value <= mount:
                heights.append(mount - value)
    options = config['automatik']
    target = None
    if expected and len(heights) == expected:
        ceiling = max(0.0, config['wasserstand']['max_fuellhoehe_cm'] - options['pumpe_hysterese_cm'])
        target = max(0.0, min(sum(heights) / len(heights) - options['wasser_unter_moosspitzen_cm'], ceiling))
    return {'target_cm': target, 'moss_distances_cm': distances}


def pump_ready(data):
    return bool(data and data.get('water_ready') and data.get('pump_allowed')
                and valid_number(data.get('target_cm')) and valid_number(data.get('water_level_cm')))


class PumpRegulator:
    def __init__(self):
        self.reset()

    def reset(self):
        self.state = 'blocked'
        self.below_since = None
        self.reason = 'Freigabe erforderlich'

    def value(self, data, options, now):
        if not pump_ready(data):
            self.reset()
            self.reason = 'Messwerte fehlen oder Sicherheitsgrenze erreicht'
            return 0
        target, level = data['target_cm'], data['water_level_cm']
        if target <= 0 or level >= target:
            self.state = 'waiting'
            self.below_since = None
            self.reason = 'Zielbereich'
            return 0
        if self.state != 'filling':
            self.state = 'waiting'
            if level >= target - options['pumpe_hysterese_cm']:
                self.below_since = None
                self.reason = 'Zielbereich'
                return 0
            if self.below_since is None:
                self.below_since = now
            self.reason = 'Warte auf bestätigten niedrigen Wasserstand'
            if now - self.below_since < PUMP_START_CONFIRM_SECONDS:
                return 0
        self.state = 'filling'
        self.reason = 'Wasser wird nachgefüllt'
        return options['pumpe_leistung_prozent']
