"""Shared measurement rules; all filter and freshness thresholds live here."""
import math
import statistics
from collections import deque

MAX_DISTANCE_CM = 400
MAX_SAMPLE_AGE_SECONDS = 12
WATER_MAX_AGE_SECONDS = 3
SNAPSHOT_MAX_AGE_SECONDS = 5
FILTER_SAMPLES = 15
MIN_STABLE_PERCENT = 80
WATER_SPREAD_CM = 0.2
MOSS_SPREAD_CM = 0.3
PUMP_START_CONFIRM_SECONDS = 30
CONTROL_INTERVAL_SECONDS = 0.1
SOUND_CM_PER_SECOND = 34300
ECHO_TIMEOUT_SECONDS = 0.05
TRIGGER_SECONDS = 0.00001


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fresh(sampled, now, max_age=MAX_SAMPLE_AGE_SECONDS):
    return valid_number(sampled) and 0 <= now - sampled <= max_age


def required_inliers(sample_count, min_percent):
    return (sample_count * min_percent + 99) // 100


class DistanceFilter:
    def __init__(self, spread_cm, sample_count=FILTER_SAMPLES, min_percent=MIN_STABLE_PERCENT,
                 max_gap_seconds=MAX_SAMPLE_AGE_SECONDS):
        self.spread_cm = spread_cm
        self.sample_count = sample_count
        self.min_percent = min_percent
        self.max_gap_seconds = max_gap_seconds
        self.samples = deque(maxlen=sample_count)
        self.last_sample = None

    @classmethod
    def from_settings(cls, settings, sensor):
        if settings is None:
            return cls(WATER_SPREAD_CM if sensor == 'wasser' else MOSS_SPREAD_CM)
        return cls(settings[f'{sensor}_streuung_cm'], settings['messungen'],
                   settings['mindestanteil_prozent'], settings['max_messpause_s'])

    def update(self, distance, now):
        if self.last_sample is not None and not fresh(self.last_sample, now, self.max_gap_seconds):
            self.samples.clear()
        self.last_sample = now
        if not valid_number(distance) or not 0 < distance <= MAX_DISTANCE_CM:
            self.samples.clear()
            return None
        self.samples.append(distance)
        result = {'distance_cm': distance, 'measurement_stable': 0}
        if len(self.samples) == self.sample_count:
            median = statistics.median(self.samples)
            inliers = [value for value in self.samples if abs(value - median) <= self.spread_cm]
            if len(inliers) >= required_inliers(self.sample_count, self.min_percent):
                result.update(distance_filtered_cm=statistics.median(inliers), measurement_stable=1)
        return result
