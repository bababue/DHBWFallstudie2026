"""Ultrasonic distance measurement and water depth in the tank."""

import time
from threading import Event, Lock
from measurements import (DistanceFilter, MAX_DISTANCE_CM,
                          SOUND_CM_PER_SECOND, ECHO_TIMEOUT_SECONDS, TRIGGER_SECONDS)


class TimestampUltrasonic:
    """Measure ultrasonic echo width from kernel edge timestamps."""

    SOUND_CM_PER_S = SOUND_CM_PER_SECOND
    MAX_DISTANCE_CM = MAX_DISTANCE_CM

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
        time.sleep(TRIGGER_SECONDS)
        self.gpio.gpio_write(self.handle, self.trigger_pin, 0)
        self._done.wait(ECHO_TIMEOUT_SECONDS)
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

    def __init__(self, gpio, handle, trigger_pin, echo_pin, floor_distance_cm, max_level, filter_settings=None):
        super().__init__(gpio, handle, trigger_pin, echo_pin)
        self.floor_distance_cm = floor_distance_cm
        self.max_level = max_level
        self.filter = DistanceFilter.from_settings(filter_settings, 'wasser')

    def read(self):
        result = self.filter.update(self._distance_cm(), time.monotonic())
        if result is not None:
            result['max_level_reached'] = int(self.floor_distance_cm - result['distance_cm'] >= self.max_level)
            if result['measurement_stable']:
                result['water_level_cm'] = max(0.0, self.floor_distance_cm - result['distance_filtered_cm'])
        return result
