"""LED, fan and pump PWM outputs for the Raspberry Pi dashboard."""

import logging
import re
import threading


LOG = logging.getLogger("moos.actuators")


class PumpLocked(Exception):
    """The pump cannot run without a valid safe water level."""


class Actuators:
    BOOST_SECONDS = 0.5
    BOOSTS = {"fan": (50, 100)}
    MIN_DUTY = {"fan": 25}

    def __init__(self, gpio, chip: str, led_pin: int, fan_pin: int, pump_pin: int,
                 led_hz: int, fan_hz: int, pump_hz: int, pump_allowed=None):
        if not re.fullmatch(r"/dev/gpiochip\d+", chip):
            raise ValueError("GPIOCHIP_DEVICE must be /dev/gpiochipN")
        self.pins = {"led": led_pin, "fan": fan_pin, "pump": pump_pin}
        self.frequencies = {"led": led_hz, "fan": fan_hz, "pump": pump_hz}
        if len(set(self.pins.values())) != len(self.pins) or not all(0 <= pin <= 27 for pin in self.pins.values()):
            raise ValueError("LED, fan and pump need distinct BCM GPIO pins")
        if not all(hz > 0 for hz in self.frequencies.values()):
            raise ValueError("PWM frequencies must be positive")
        self.pump_allowed = pump_allowed or (lambda: False)
        self.gpio = gpio
        self.lock = threading.RLock()
        self.values = {device: 0 for device in self.pins}
        self.timers = {device: None for device in self.BOOSTS}
        self.generations = {device: 0 for device in self.BOOSTS}
        self.closed = False
        self.handle = gpio.gpiochip_open(int(chip.removeprefix("/dev/gpiochip")))
        try:
            for pin in self.pins.values():
                gpio.gpio_claim_output(self.handle, pin, 0)
        except Exception:
            gpio.gpiochip_close(self.handle)
            raise

    def status(self) -> dict[str, int]:
        with self.lock:
            return dict(self.values)

    @staticmethod
    def duty(device: str, value: int) -> float:
        if value == 0:
            return 0
        if device in ("led", "pump"):
            return value
        minimum = Actuators.MIN_DUTY[device]
        return minimum + (value - 5) * (100 - minimum) / 95

    def _apply(self, pin: int, hz: int, duty: float):
        if duty <= 0 or duty >= 100:
            if self.gpio.tx_busy(self.handle, pin, self.gpio.TX_PWM):
                self.gpio.tx_pwm(self.handle, pin, 0, 0)
            self.gpio.gpio_write(self.handle, pin, 1 if duty >= 100 else 0)
        else:
            self.gpio.tx_pwm(self.handle, pin, hz, duty)

    def set(self, device: str, value: int) -> dict[str, int]:
        if device not in self.values or type(value) is not int or not (value == 0 or 5 <= value <= 100):
            raise ValueError("Device must be led, fan or pump and value 0 or an integer 5..100")
        with self.lock:
            if self.closed:
                raise RuntimeError("GPIO controller is closed")
            if device == 'pump' and value > 0:
                raise PumpLocked('Pumpe ist deaktiviert')
            pin, hz = self.pins[device], self.frequencies[device]
            old = self.values[device]
            if device in self.BOOSTS:
                self.generations[device] += 1
                if self.timers[device] is not None:
                    self.timers[device].cancel()
                    self.timers[device] = None
            boost = self.BOOSTS.get(device)
            if boost is not None and old == 0 and 0 < value <= boost[0]:
                self._apply(pin, hz, boost[1])
                self.values[device] = value
                timer = threading.Timer(self.BOOST_SECONDS, self._finish_boost,
                                        (device, self.generations[device]))
                timer.daemon = True
                self.timers[device] = timer
                timer.start()
            else:
                self._apply(pin, hz, self.duty(device, value))
            self.values[device] = value
            return dict(self.values)

    def _finish_boost(self, device: str, generation: int):
        with self.lock:
            if self.closed or generation != self.generations[device]:
                return
            self.timers[device] = None
            try:
                self._apply(self.pins[device], self.frequencies[device],
                            self.duty(device, self.values[device]))
            except Exception:
                LOG.exception("Could not finish %s startup boost; switching off", device)
                self.values[device] = 0
                self._apply(self.pins[device], self.frequencies[device], 0)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            for device in self.BOOSTS:
                self.generations[device] += 1
                if self.timers[device] is not None:
                    self.timers[device].cancel()
            try:
                for device, pin in self.pins.items():
                    try:
                        self._apply(pin, self.frequencies[device], 0)
                    except Exception:
                        LOG.exception("Could not switch off %s during shutdown", device)
            finally:
                self.gpio.gpiochip_close(self.handle)
