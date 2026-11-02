"""Calibrated moss height from two staggered ultrasonic sensors."""

import statistics
import time
from collections import deque

from water_level import Ultrasonic


class MossHeight(Ultrasonic):
    name = "ultrasonic"
    WINDOW_S = 60

    def __init__(self, gpio, handle, trigger_pin, echo_pin, empty_distance_cm=None):
        super().__init__(gpio, handle, trigger_pin, echo_pin)
        self.empty_distance_cm = empty_distance_cm
        self.recent_distances = deque()

    def read(self):
        distance = self._distance_cm()
        if distance is None:
            return None
        now = time.monotonic()
        self.recent_distances.append((now, distance))
        while self.recent_distances and self.recent_distances[0][0] < now - self.WINDOW_S:
            self.recent_distances.popleft()
        result = {"distance_cm": distance}
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
