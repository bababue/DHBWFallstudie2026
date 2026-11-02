"""Ultrasonic distance measurement and water depth in the tank."""

import statistics
import time
from collections import deque
from threading import Event, Lock


class Ultrasonic:
    SOUND_CM_PER_S = 34300
    MAX_DISTANCE_CM = 400
    START_TIMEOUT_S = 0.01

    def __init__(self, gpio, handle: int, trigger_pin: int, echo_pin: int, pull_down=False):
        self.gpio = gpio
        self.handle = handle
        self.trigger_pin = trigger_pin
        self.echo_pin = echo_pin
        gpio.gpio_claim_output(handle, trigger_pin, 0)
        try:
            gpio.gpio_claim_input(handle, echo_pin, gpio.SET_PULL_DOWN) if pull_down else gpio.gpio_claim_input(handle, echo_pin)
        except Exception:
            gpio.gpio_free(handle, trigger_pin)
            raise

    def _distance_cm(self):
        self.gpio.gpio_write(self.handle, self.trigger_pin, 1)
        time.sleep(0.00001)
        self.gpio.gpio_write(self.handle, self.trigger_pin, 0)

        deadline = time.perf_counter() + self.START_TIMEOUT_S
        while not self.gpio.gpio_read(self.handle, self.echo_pin):
            if time.perf_counter() >= deadline:
                return None
        start = time.perf_counter()
        echo_timeout = 2 * self.MAX_DISTANCE_CM / self.SOUND_CM_PER_S
        while self.gpio.gpio_read(self.handle, self.echo_pin):
            if time.perf_counter() - start >= echo_timeout:
                return None
        return (time.perf_counter() - start) * self.SOUND_CM_PER_S / 2

    def close(self):
        self.gpio.gpio_write(self.handle, self.trigger_pin, 0)
        self.gpio.gpio_free(self.handle, self.echo_pin)
        self.gpio.gpio_free(self.handle, self.trigger_pin)


class TimestampUltrasonic(Ultrasonic):
    """Measure echo width from kernel edge timestamps, not Python polling."""

    def __init__(self, gpio, handle, trigger_pin, echo_pin):
        self.gpio, self.handle = gpio, handle
        self.trigger_pin, self.echo_pin = trigger_pin, echo_pin
        self._lock = Lock()
        self._done = Event()
        self._armed = False
        self._rise = None
        self._distance = None
        gpio.gpio_claim_output(handle, trigger_pin, 0)
        try:
            gpio.gpio_claim_alert(handle, echo_pin, gpio.BOTH_EDGES)
            self._callback = gpio.callback(handle, echo_pin, gpio.BOTH_EDGES, self._edge)
        except Exception:
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
        super().close()


class WaterLevel(TimestampUltrasonic):
    name = "ultrasonic"

    def __init__(self, gpio, handle, trigger_pin, echo_pin, floor_distance_cm,
                 options=None):
        super().__init__(gpio, handle, trigger_pin, echo_pin)
        options = options or {}
        self.floor_distance_cm = floor_distance_cm
        self.count = options.get('filter_messungen', 5)
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
        if len(inliers) < self.count // 2 + 1:
            return result
        stable = statistics.median(inliers)
        result.update({'measurement_stable': 1, 'distance_filtered_cm': stable,
                       'water_level_cm': max(0.0, self.floor_distance_cm - stable)})
        if self.max_level is not None:
            result['max_level_reached'] = int(result['max_level_reached'] or result['water_level_cm'] >= self.max_level)
        return result
