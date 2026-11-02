"""Ultrasonic water depth in the tank, measured from the sensor above its floor."""

import statistics
import time


class WaterLevel:
    name = "ultrasonic"
    SOUND_CM_PER_S = 34300
    MAX_DISTANCE_CM = 400
    START_TIMEOUT_S = 0.01
    SAMPLE_PAUSE_S = 0.06
    SAMPLES = 5

    def __init__(self, gpio, handle: int, trigger_pin: int, echo_pin: int,
                 floor_distance_cm: float):
        self.gpio = gpio
        self.handle = handle
        self.trigger_pin = trigger_pin
        self.echo_pin = echo_pin
        self.floor_distance_cm = floor_distance_cm
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

    def read(self):
        distances = []
        for index in range(self.SAMPLES):
            distance = self._distance_cm()
            if distance is not None:
                distances.append(distance)
            if index < self.SAMPLES - 1:
                time.sleep(self.SAMPLE_PAUSE_S)
        if not distances:
            return None
        distance = statistics.median(distances)
        return {
            "distance_cm": distance,
            "water_level_cm": max(0.0, self.floor_distance_cm - distance),
        }

    def close(self):
        self.gpio.gpio_write(self.handle, self.trigger_pin, 0)
        self.gpio.gpio_free(self.handle, self.echo_pin)
        self.gpio.gpio_free(self.handle, self.trigger_pin)
