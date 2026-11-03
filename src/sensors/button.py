"""Debounced GPIO button state for the OLED's display modes."""

import json
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
                    if self._pressed_since is not None and now - self._pressed_since < self.HOLD_SECONDS:
                        self._mode = (self._mode + 1) % len(MODES)
                    self._show_info = False
                    self._pressed_since = None
                self._version += 1
            if (self._pressed and not self._show_info and self._pressed_since is not None
                    and now - self._pressed_since >= self.HOLD_SECONDS):
                self._show_info = True
                self._version += 1

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError('Unbekannter Modus')
        with self._lock:
            index = MODES.index(mode)
            if self._mode != index:
                self._mode = index
                self._version += 1

    def snapshot(self):
        with self._lock:
            return MODES[self._mode], self._show_info, self._version


def apply_mode_command(modes, path, previous_id, now):
    """Apply a fresh command once; ignore malformed or stale requests."""
    try:
        with open(path) as request:
            command = json.load(request)
        command_id, target, requested = command['id'], command['mode'], command['requested']
        if (isinstance(command_id, str) and command_id != previous_id
                and target in MODES and isinstance(requested, (int, float))
                and not isinstance(requested, bool) and 0 <= now - requested <= 5):
            modes.set_mode(target)
            return command_id
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return previous_id


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
