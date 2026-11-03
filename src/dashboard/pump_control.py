"""Moss-relative water target and continuous pump control."""
import math
import json
import statistics
import time
from threading import Lock


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def target_level(config, moss_height):
    maximum = config['wasserstand']['max_fuellhoehe_cm']
    if maximum is None:
        return None
    options = config['automatik']
    if options.get('zielwasserstand_fest', False):
        desired = options['zielwasserstand_cm']
    elif valid_number(moss_height):
        desired = moss_height - options['wasser_unter_moosspitzen_cm']
    else:
        return None
    ceiling = maximum - config['wasserstand']['sicherheitsabstand_cm'] - options['pumpe_hysterese_cm']
    return max(0.0, min(desired, ceiling))


def pump_ready(data):
    return bool(data and data.get('water_ready') and data.get('pump_allowed')
                and all(valid_number(data.get(key))
                        for key in ('target_cm', 'water_level_cm', 'raw_level_cm')))


def water_overview(readings, config, now):
    """Derive the target from the mean of fresh, smoothed moss tip heights."""
    heights = []
    for reading in readings:
        if (reading.get('side') in ('moss1', 'moss2', 'moss3', 'moss4')
                and reading.get('sensor') == 'ultrasonic' and reading.get('field') == 'height_median_1m_cm'
                and valid_number(reading.get('sampled')) and 0 <= now - reading['sampled'] <= 12
                and valid_number(reading.get('value')) and reading['value'] >= 0):
            heights.append(reading['value'])
    height = sum(heights) / len(heights) if heights else None
    target = target_level(config, height)
    fixed = config['automatik'].get('zielwasserstand_fest', False)
    return {'moss_height_cm': height, 'moss_averaged': len(heights) > 1, 'target_cm': target,
            'target_source': 'fixed' if fixed else 'moss',
            'target_limited': bool(fixed and target is not None and target < config['automatik']['zielwasserstand_cm'])}


class StableWaterTarget:
    """Confirm a consistent set of stable moss readings before changing the target."""

    CONFIRM_SECONDS = 180
    MAX_SPREAD_CM = 0.2
    DEADBAND_CM = 0.1

    def __init__(self):
        self.lock = Lock()
        self.signature = None
        self.reset()

    def reset(self):
        self.height = None
        self.candidate = []
        self.last_sample = None

    def update(self, readings, config, now):
        with self.lock:
            signature = json.dumps(config, sort_keys=True)
            if signature != self.signature:
                self.reset()
                self.signature = signature
            result = water_overview(readings, config, now)
            if config['automatik'].get('zielwasserstand_fest', False):
                return result
            expected = {f'moss{i}' for i in range(1, 5)
                        if config.get(f'moos_{i}', {}).get('bezugsabstand_cm') is not None}
            fresh = {(r['side'], r['field']): r for r in readings
                     if r.get('sensor') == 'ultrasonic' and r.get('side') in expected
                     and valid_number(r.get('sampled')) and 0 <= now - r['sampled'] <= 12}
            heights = []
            samples = []
            for side in expected:
                height = fresh.get((side, 'height_median_1m_cm'), {})
                stable = fresh.get((side, 'measurement_stable'), {})
                if (not valid_number(height.get('value')) or height['value'] < 0
                        or stable.get('value') != 1
                        or height.get('sampled') != stable.get('sampled')):
                    self.reset()
                    result['target_cm'] = None
                    return result
                heights.append(height['value'])
                samples.append(height['sampled'])
            if not heights:
                self.reset()
                result['target_cm'] = None
                return result
            sampled = min(samples)
            height = statistics.mean(heights)
            if self.last_sample is not None and (sampled < self.last_sample or sampled - self.last_sample > 12):
                self.reset()
            if sampled != self.last_sample:
                self.last_sample = sampled
                if self.height is not None and abs(height - self.height) <= self.DEADBAND_CM:
                    self.candidate = []
                else:
                    values = [value for _, value in self.candidate] + [height]
                    if max(values) - min(values) > self.MAX_SPREAD_CM:
                        self.candidate = []
                    self.candidate.append((sampled, height))
                    if sampled - self.candidate[0][0] >= self.CONFIRM_SECONDS:
                        self.height = statistics.median(value for _, value in self.candidate)
                        self.candidate = []
            result['target_cm'] = target_level(config, self.height)
            return result


class PumpRegulator:
    """Confirm low water before filling; stop immediately on high or unsafe readings."""

    LOW_WATER_CONFIRM_SECONDS = 30

    def __init__(self):
        self.reset()

    def reset(self):
        self.reached = False
        self.reason = ''
        self.running = False
        self.below_since = None

    def value(self, data, options, now=None):
        now = time.monotonic() if now is None else now
        if not pump_ready(data):
            self.running = False
            self.below_since = None
            self.reason = 'Warte auf sichere Messwerte'
            return 0
        target, level = data['target_cm'], data['water_level_cm']
        if target <= 0 or max(level, data['raw_level_cm']) >= target:
            self.reached = True
            self.running = False
            self.below_since = None
            self.reason = 'Zielwasserstand erreicht'
            return 0
        if self.reached and max(level, data['raw_level_cm']) >= target - options['pumpe_hysterese_cm']:
            self.running = False
            self.below_since = None
            self.reason = 'Zielwasserstand erreicht'
            return 0
        if not self.running:
            if self.below_since is None:
                self.below_since = now
            if now - self.below_since < self.LOW_WATER_CONFIRM_SECONDS:
                self.reason = 'Warte auf bestätigten niedrigen Wasserstand'
                return 0
            self.running = True
        self.reached = False
        self.reason = 'Wasser wird nachgefüllt'
        return options['pumpe_leistung_prozent']
