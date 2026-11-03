"""Calibrated moss height from staggered ultrasonic sensors."""

import statistics
import time
from collections import deque

from water_level import TimestampUltrasonic


class MossHeight(TimestampUltrasonic):
    name = "ultrasonic"
    WINDOW_S = 60
    PLATFORM_HEIGHT_CM = 6.0

    def __init__(self, gpio, handle, trigger_pin, echo_pin, empty_distance_cm=None):
        super().__init__(gpio, handle, trigger_pin, echo_pin, pull_down=True)
        self.empty_distance_cm = empty_distance_cm
        self.recent_distances = deque()

    def read(self):
        distance = super()._distance_cm()
        if distance is None or not 0 < distance <= self.MAX_DISTANCE_CM:
            return None
        now = time.monotonic()
        self.recent_distances.append((now, distance))
        while self.recent_distances and self.recent_distances[0][0] < now - self.WINDOW_S:
            self.recent_distances.popleft()
        result = {"distance_cm": distance}
        if self.empty_distance_cm is not None:
            result["height_cm"] = max(0.0, self.PLATFORM_HEIGHT_CM + self.empty_distance_cm - result["distance_cm"])
            minute_distance = statistics.median(value for _, value in self.recent_distances)
            result["height_median_1m_cm"] = max(0.0, self.PLATFORM_HEIGHT_CM + self.empty_distance_cm - minute_distance)
            inliers = sum(abs(value - minute_distance) <= 0.3 for _, value in self.recent_distances)
            result['measurement_stable'] = int(len(self.recent_distances) >= 5
                                               and inliers >= len(self.recent_distances) * 0.8)
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
