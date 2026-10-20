
"""Zeigt den gemessenen Abstand auf dem OLED des Raspberry Pi."""

import time

from gpiozero import DistanceSensor
from gpiozero.pins.lgpio import LGPIOFactory
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import ImageFont


OLED_ADDRESS = 0x3C
OLED_WIDTH = 128
OLED_HEIGHT = 64
TRIGGER_GPIO = 5
ECHO_GPIO = 6


def lade_schriftgroesse(groesse):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", groesse)
    except OSError:
        return ImageFont.load_default()


def main():
    serial = i2c(port=1, address=OLED_ADDRESS)
    display = ssd1306(serial, width=OLED_WIDTH, height=OLED_HEIGHT)
    sensor = DistanceSensor(
        echo=ECHO_GPIO,
        trigger=TRIGGER_GPIO,
        max_distance=4,
        queue_len=5,
        pin_factory=LGPIOFactory(),
    )
    wert_schrift = lade_schriftgroesse(23)
    print("Abstandssensor gestartet")

    try:
        while True:
            abstand_cm = sensor.distance * 100
            with canvas(display) as draw:
                draw.text((4, 19), f"{abstand_cm:.1f} cm", font=wert_schrift, fill="white")
            time.sleep(1)
    except KeyboardInterrupt:
        print("Programm beendet")
    finally:
        display.clear()
        sensor.close()


if __name__ == "__main__":
    main()

