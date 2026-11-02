"""Debounced GPIO button state for the OLED's display modes."""

import logging
import time
from threading import Lock, Thread


LOG = logging.getLogger("moos.button")
MODES = ("AUTO", "MAINTENANCE")


class ButtonModes:
    DEBOUNCE_SECONDS = 0.04
    HOLD_SECONDS = 0.6

    def __init__(self):
        self._lock = Lock()
        self._raw = False
        self._raw_since = 0.0
        self._pressed = False
        self._pressed_since = None
        self._show_info = False
        self._mode = 0
        self._version = 0
        self._lid_open = False

    def feed(self, pressed, now):
        with self._lock:
            if pressed != self._raw:
                self._raw = pressed
                self._raw_since = now
            if self._pressed != self._raw and now - self._raw_since >= self.DEBOUNCE_SECONDS:
                self._pressed = self._raw
                if self._pressed:
                    self._pressed_since = now
                else:
                    if not self._lid_open and self._pressed_since is not None and now - self._pressed_since < self.HOLD_SECONDS:
                        self._mode = (self._mode + 1) % len(MODES)
                    self._show_info = False
                    self._pressed_since = None
                self._version += 1
            if (self._pressed and not self._show_info and self._pressed_since is not None
                    and now - self._pressed_since >= self.HOLD_SECONDS):
                self._show_info = True
                self._version += 1

    def set_lid_open(self, is_open):
        with self._lock:
            if self._lid_open == is_open:
                return
            self._lid_open = is_open
            self._mode = MODES.index("MAINTENANCE" if is_open else "AUTO")
            self._version += 1

    def snapshot(self):
        with self._lock:
            return MODES[self._mode], self._show_info, self._version


def start_button_reader(gpio, handle, pin, stop, modes):
    """Sample independently so sensor reads cannot swallow short presses."""
    gpio.gpio_claim_input(handle, pin, gpio.SET_PULL_UP)

    def read_loop():
        while not stop.wait(0.02):
            try:
                modes.feed(gpio.gpio_read(handle, pin) == 0, time.monotonic())
            except Exception:
                LOG.exception("Button read failed")
                return

    thread = Thread(target=read_loop, name="moos-button", daemon=True)
    thread.start()
    return thread
