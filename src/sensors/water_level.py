"""Ultrasonic distance measurement and water depth in the tank."""

import statistics
import time
from collections import deque


class Ultrasonic:
    SOUND_CM_PER_S = 34300
    MAX_DISTANCE_CM = 400
    START_TIMEOUT_S = 0.01

    def __init__(self, gpio, handle: int, trigger_pin: int, echo_pin: int):
        self.gpio = gpio
        self.handle = handle
        self.trigger_pin = trigger_pin
        self.echo_pin = echo_pin
        gpio.gpio_claim_output(handle, trigger_pin, 0)
        try:
            gpio.gpio_claim_input(handle, echo_pin)
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


class WaterLevel(Ultrasonic):
    name = "ultrasonic"
    MEDIAN_WINDOW_S = 60

    def __init__(self, gpio, handle: int, trigger_pin: int, echo_pin: int,
                 floor_distance_cm: float):
        super().__init__(gpio, handle, trigger_pin, echo_pin)
        self.floor_distance_cm = floor_distance_cm
        self.recent_distances = deque()

    def read(self):
        distance = self._distance_cm()
        if distance is None:
            return None
        now = time.monotonic()
        self.recent_distances.append((now, distance))
        while self.recent_distances and self.recent_distances[0][0] < now - self.MEDIAN_WINDOW_S:
            self.recent_distances.popleft()
        minute_distance = statistics.median(value for _, value in self.recent_distances)
        return {
            "distance_cm": distance,
            "water_level_cm": max(0.0, self.floor_distance_cm - distance),
            "water_level_median_1m_cm": max(0.0, self.floor_distance_cm - minute_distance),
        }
