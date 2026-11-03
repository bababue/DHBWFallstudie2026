"""Ultrasonic distance measurement and water depth in the tank."""

import statistics
import math
import time
from collections import deque
from threading import Event, Lock


class TimestampUltrasonic:
    """Measure ultrasonic echo width from kernel edge timestamps."""

    SOUND_CM_PER_S = 34300
    MAX_DISTANCE_CM = 400

    def __init__(self, gpio, handle, trigger_pin, echo_pin, pull_down=False):
        self.gpio, self.handle = gpio, handle
        self.trigger_pin, self.echo_pin = trigger_pin, echo_pin
        self._lock = Lock()
        self._done = Event()
        self._armed = False
        self._rise = None
        self._distance = None
        gpio.gpio_claim_output(handle, trigger_pin, 0)
        claimed_echo = False
        try:
            if pull_down:
                gpio.gpio_claim_alert(handle, echo_pin, gpio.BOTH_EDGES, gpio.SET_PULL_DOWN)
            else:
                gpio.gpio_claim_alert(handle, echo_pin, gpio.BOTH_EDGES)
            claimed_echo = True
            self._callback = gpio.callback(handle, echo_pin, gpio.BOTH_EDGES, self._edge)
        except Exception:
            if claimed_echo:
                gpio.gpio_free(handle, echo_pin)
            gpio.gpio_free(handle, trigger_pin)
            raise

    def _edge(self, chip, pin, level, tick):
        with self._lock:
            if not self._armed:
                return
            if level == 1:
                self._rise = tick
            elif level == 0 and self._rise is not None:
                duration = (tick - self._rise) / 1_000_000_000
                if duration > 0:
                    self._distance = duration * self.SOUND_CM_PER_S / 2
                self._armed = False
                self._done.set()

    def _distance_cm(self):
        with self._lock:
            self._done.clear()
            self._rise = self._distance = None
            self._armed = True
        self.gpio.gpio_write(self.handle, self.trigger_pin, 1)
        time.sleep(.00001)
        self.gpio.gpio_write(self.handle, self.trigger_pin, 0)
        self._done.wait(.05)
        with self._lock:
            self._armed = False
            return self._distance

    def close(self):
        self._callback.cancel()
        self.gpio.gpio_write(self.handle, self.trigger_pin, 0)
        self.gpio.gpio_free(self.handle, self.echo_pin)
        self.gpio.gpio_free(self.handle, self.trigger_pin)


class WaterLevel(TimestampUltrasonic):
    name = "ultrasonic"

    def __init__(self, gpio, handle, trigger_pin, echo_pin, floor_distance_cm,
                 options=None):
        super().__init__(gpio, handle, trigger_pin, echo_pin)
        options = options or {}
        self.floor_distance_cm = floor_distance_cm
        self.count = options.get('filter_messungen', 15)
        self.max_spread = options.get('max_streuung_cm', .2)
        self.max_level = options.get('max_fuellhoehe_cm')
        self.recent = deque(maxlen=self.count)
        self.last_sample = None

    def read(self):
        distance = self._distance_cm()
        now = time.monotonic()
        if self.last_sample is not None and now - self.last_sample > 12:
            self.recent.clear()
        self.last_sample = now
        if distance is None or not 0 < distance <= self.MAX_DISTANCE_CM:
            self.recent.clear()
            return None
        self.recent.append(distance)
        result = {'distance_cm': distance, 'measurement_stable': 0,
                  'max_level_configured': int(self.max_level is not None)}
        # An upper-limit observation is never suppressed by smoothing.
        if self.max_level is not None:
            result['max_level_reached'] = int(self.floor_distance_cm - distance >= self.max_level)
        if len(self.recent) < self.count:
            return result
        median = statistics.median(self.recent)
        inliers = [v for v in self.recent if abs(v - median) <= self.max_spread]
        if len(inliers) < math.ceil(self.count * 0.8):
            return result
        stable = statistics.median(inliers)
        result.update({'measurement_stable': 1, 'distance_filtered_cm': stable,
                       'water_level_cm': max(0.0, self.floor_distance_cm - stable)})
        if self.max_level is not None:
            result['max_level_reached'] = int(result['max_level_reached'] or result['water_level_cm'] >= self.max_level)
        return result
