
"""Zeigt Shrek auf dem OLED des Raspberry Pi."""

import time
from pathlib import Path

from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageOps


OLED_ADDRESS = 0x3C
OLED_WIDTH = 128
OLED_HEIGHT = 64
BILD_PFAD = Path(__file__).with_name("shrek.png")


def lade_bild():
    """Bereitet das lokale Shrek-Bild fuer das OLED auf."""
    with Image.open(BILD_PFAD) as quelle:
        hintergrund = Image.new("RGBA", quelle.size, "white")
        hintergrund.alpha_composite(quelle.convert("RGBA"))
        ausschnitt = ImageOps.fit(
            hintergrund.convert("L"),
            (OLED_WIDTH, OLED_HEIGHT),
            method=Image.LANCZOS,
            centering=(0.5, 0.12),
        )
        return ImageOps.autocontrast(ausschnitt).convert("1")


def main():
    serial = i2c(port=1, address=OLED_ADDRESS)
    display = ssd1306(serial, width=OLED_WIDTH, height=OLED_HEIGHT)
    bild = lade_bild()
    display.clear()
    print("Shrek wird alle 10 Sekunden kurz angezeigt")

    try:
        while True:
            time.sleep(10)
            display.display(bild)
            time.sleep(1)
            display.clear()
    except KeyboardInterrupt:
        print("Programm beendet")
    finally:
        display.clear()


if __name__ == "__main__":
    main()

