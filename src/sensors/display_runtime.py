"""Run the OLED and button beside the sensor loop on the shared left I2C bus."""

import json
import logging
import time
from urllib.request import Request, urlopen

from display import ButtonMenu
from oled import Oled, render


LOG = logging.getLogger("moos.display")
CONTROL_URL = "http://dashboard:8080/api/controls"


class ControlClient:
    def __init__(self, password):
        self.password = password

    def _request(self, payload=None):
        headers = {"X-Control-Password": self.password}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = Request(CONTROL_URL,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers=headers)
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    def status(self):
        return self._request()

    def set(self, device, value):
        return self._request({"device": device, "value": value})


def run_display(gpio, handle, button_pin, bus, bus_lock, readings, readings_lock,
                password, stop):
    client = ControlClient(password)
    controls = {"led": 0, "pump": 0, "fan": 0}
    enabled = False
    dirty = True
    previous_level = 1
    stable_level = 1
    next_status = 0.0
    next_refresh = 0.0
    oled = Oled(bus)

    def set_value(device, value):
        nonlocal controls, enabled, dirty
        if not enabled:
            return
        try:
            result = client.set(device, value)
            controls = result["values"]
            dirty = True
        except Exception as error:
            enabled = False
            dirty = True
            LOG.warning("OLED control failed: %s", error)

    menu = ButtonMenu(set_value)
    gpio.gpio_claim_input(handle, button_pin, gpio.SET_PULL_UP)
    try:
        while not stop.is_set():
            now = time.monotonic()
            level = gpio.gpio_read(handle, button_pin)
            if level == previous_level:
                stable_level = level
            previous_level = level
            if menu.tick(stable_level == 0, now, controls):
                dirty = True

            if now >= next_status:
                next_status = now + 1.0
                try:
                    status = client.status()
                    if status["enabled"] != enabled or status["values"] != (controls if enabled else {}):
                        dirty = True
                    enabled = status["enabled"]
                    if enabled:
                        controls = status["values"]
                except Exception as error:
                    if enabled:
                        dirty = True
                    enabled = False
                    LOG.debug("OLED control status unavailable: %s", error)

            if dirty or now >= next_refresh:
                with readings_lock:
                    snapshot = dict(readings)
                try:
                    image = render(menu.view, snapshot, controls, enabled)
                    with bus_lock:
                        oled.zeigen(image)
                    dirty = False
                except Exception as error:
                    LOG.warning("OLED update failed: %s", error)
                next_refresh = now + 1.0
            stop.wait(0.02)
    finally:
        try:
            with bus_lock:
                oled.ausschalten()
        except Exception:
            pass
        gpio.gpio_free(handle, button_pin)
