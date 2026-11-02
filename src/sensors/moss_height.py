"""Calibrated moss height from staggered ultrasonic sensors."""

import statistics
import random
import time
from collections import deque

from water_level import TimestampUltrasonic


class WaterNoise:
    """Estimate water distance dispersion from the last minute of raw echoes."""

    WINDOW_S = 60
    MIN_SAMPLES = 5

    def __init__(self):
        self.samples = deque()

    def add(self, now, value):
        self.samples.append((now, value))

    def sigma(self, now):
        while self.samples and self.samples[0][0] < now - self.WINDOW_S:
            self.samples.popleft()
        if len(self.samples) < self.MIN_SAMPLES:
            return None
        return statistics.stdev(value for _, value in self.samples)


class MossHeight(TimestampUltrasonic):
    name = "ultrasonic"
    WINDOW_S = 60

    def __init__(self, gpio, handle, trigger_pin, echo_pin, empty_distance_cm=None,
                 demo_distance_cm=None, demo_sigma_cm=None):
        self.demo_distance_cm = demo_distance_cm
        self.demo_sigma_cm = demo_sigma_cm
        if demo_distance_cm is None:
            super().__init__(gpio, handle, trigger_pin, echo_pin, pull_down=True)
        self.empty_distance_cm = (demo_distance_cm if empty_distance_cm is None and demo_distance_cm is not None
                                  else empty_distance_cm)
        self.recent_distances = deque()

    def _distance_cm(self):
        if self.demo_distance_cm is not None:
            if self.demo_sigma_cm is None:
                return None
            return max(0.001, min(self.MAX_DISTANCE_CM, random.gauss(self.demo_distance_cm, self.demo_sigma_cm)))
        return super()._distance_cm()

    def close(self):
        if self.demo_distance_cm is None:
            super().close()

    def read(self):
        distance = self._distance_cm()
        if distance is None:
            return None
        now = time.monotonic()
        self.recent_distances.append((now, distance))
        while self.recent_distances and self.recent_distances[0][0] < now - self.WINDOW_S:
            self.recent_distances.popleft()
        result = {"distance_cm": distance, "demo_data": self.demo_distance_cm is not None}
        if self.empty_distance_cm is not None:
            result["height_cm"] = max(0.0, self.empty_distance_cm - result["distance_cm"])
            minute_distance = statistics.median(value for _, value in self.recent_distances)
            result["height_median_1m_cm"] = max(0.0, self.empty_distance_cm - minute_distance)
        return result


class MossAggregate:
    """Median of both recent, individually calibrated one-minute medians."""

    MAX_AGE_S = 12
    MIN_SENSORS = 2

    def __init__(self):
        self.latest = {}

    def update(self, side, height, now=None):
        now = time.monotonic() if now is None else now
        if height is None:
            self.latest.pop(side, None)
        else:
            self.latest[side] = (now, height)
        self.latest = {name: (at, value) for name, (at, value) in self.latest.items()
                       if now - at <= self.MAX_AGE_S}
        values = [value for _, value in self.latest.values()]
        if len(values) < self.MIN_SENSORS:
            return None
        return {"height_median_cm": statistics.median(values)}


class LidMonitor:
    """Debounce each sensor independently; missing echoes never imply closure."""

    REQUIRED_READINGS = 3

    def __init__(self, threshold_cm):
        self.threshold_cm = threshold_cm
        self._state = {}
        self._pending = {}

    def update(self, side, distance):
        if distance is None or not 0 < distance <= MossHeight.MAX_DISTANCE_CM:
            self._pending.pop(side, None)
            return any(self._state.values())
        opened = distance > self.threshold_cm
        previous, count = self._pending.get(side, (None, 0))
        count = count + 1 if previous == opened else 1
        self._pending[side] = (opened, count)
        if count >= self.REQUIRED_READINGS:
            self._state[side] = opened
        return any(self._state.values())
