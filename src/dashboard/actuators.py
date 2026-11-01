"""LED and fan PWM outputs for the Raspberry Pi dashboard."""

import logging
import re
import threading


LOG = logging.getLogger("moos.actuators")


class Actuators:
    def __init__(self, gpio, chip: str, led_pin: int, fan_pin: int, led_hz: int, fan_hz: int):
        if not re.fullmatch(r"/dev/gpiochip\d+", chip):
            raise ValueError("GPIOCHIP_DEVICE must be /dev/gpiochipN")
        if led_pin == fan_pin or not all(0 <= pin <= 27 for pin in (led_pin, fan_pin)):
            raise ValueError("LED and fan need distinct BCM GPIO pins")
        if led_hz <= 0 or fan_hz <= 0:
            raise ValueError("PWM frequencies must be positive")
        self.gpio = gpio
        self.led_pin = led_pin
        self.fan_pin = fan_pin
        self.led_hz = led_hz
        self.fan_hz = fan_hz
        self.lock = threading.RLock()
        self.values = {"led": 0, "fan": 0}
        self.fan_timer = None
        self.fan_generation = 0
        self.closed = False
        self.handle = gpio.gpiochip_open(int(chip.removeprefix("/dev/gpiochip")))
        try:
            gpio.gpio_claim_output(self.handle, led_pin, 0)
            gpio.gpio_claim_output(self.handle, fan_pin, 0)
        except Exception:
            gpio.gpiochip_close(self.handle)
            raise

    def status(self) -> dict[str, int]:
        with self.lock:
            return dict(self.values)

    @staticmethod
    def fan_duty(value: int) -> float:
        if value == 0:
            return 0
        # The handover maps displayed 5% to 25% real fan duty.
        return 25 + max(value - 5, 0) * 75 / 95

    def _apply(self, pin: int, hz: int, duty: float):
        if duty <= 0 or duty >= 100:
            if self.gpio.tx_busy(self.handle, pin, self.gpio.TX_PWM):
                self.gpio.tx_pwm(self.handle, pin, 0, 0)
            self.gpio.gpio_write(self.handle, pin, 1 if duty >= 100 else 0)
        else:
            self.gpio.tx_pwm(self.handle, pin, hz, duty)

    def set(self, device: str, value: int) -> dict[str, int]:
        if device not in self.values or type(value) is not int or not 0 <= value <= 100:
            raise ValueError("Device must be led or fan and value an integer 0..100")
        with self.lock:
            if self.closed:
                raise RuntimeError("GPIO controller is closed")
            if device == "led":
                self._apply(self.led_pin, self.led_hz, value)
            else:
                old = self.values["fan"]
                self.fan_generation += 1
                if self.fan_timer is not None:
                    self.fan_timer.cancel()
                    self.fan_timer = None
                if old == 0 and 0 < value <= 50:
                    self._apply(self.fan_pin, self.fan_hz, 100)
                    generation = self.fan_generation
                    self.fan_timer = threading.Timer(1.0, self._finish_fan_boost, (generation,))
                    self.fan_timer.daemon = True
                    self.fan_timer.start()
                else:
                    self._apply(self.fan_pin, self.fan_hz, self.fan_duty(value))
            self.values[device] = value
            return dict(self.values)

    def _finish_fan_boost(self, generation: int):
        with self.lock:
            if self.closed or generation != self.fan_generation:
                return
            self.fan_timer = None
            try:
                self._apply(self.fan_pin, self.fan_hz, self.fan_duty(self.values["fan"]))
            except Exception:
                LOG.exception("Could not finish fan startup boost; switching fan off")
                self.values["fan"] = 0
                self._apply(self.fan_pin, self.fan_hz, 0)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.fan_generation += 1
            if self.fan_timer is not None:
                self.fan_timer.cancel()
            try:
                self._apply(self.led_pin, self.led_hz, 0)
            finally:
                try:
                    self._apply(self.fan_pin, self.fan_hz, 0)
                finally:
                    self.gpio.gpiochip_close(self.handle)
