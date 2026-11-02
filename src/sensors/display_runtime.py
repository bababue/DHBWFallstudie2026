"""Refresh the OLED overview on the sensor process's left I2C bus."""

import logging

from oled import Oled, render


LOG = logging.getLogger("moos.display")


def run_display(bus, bus_lock, readings, readings_lock, stop):
    oled = Oled(bus)
    try:
        while not stop.is_set():
            with readings_lock:
                snapshot = dict(readings)
            try:
                image = render(snapshot)
                with bus_lock:
                    oled.zeigen(image)
            except Exception as error:
                LOG.warning("OLED update failed: %s", error)
            stop.wait(1.0)
    finally:
        try:
            with bus_lock:
                oled.ausschalten()
        except Exception:
            pass
