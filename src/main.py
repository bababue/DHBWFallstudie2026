
"""Zeigt Shrek auf dem 128 x 64 Pixel grossen OLED des Raspberry Pi."""

import time
from pathlib import Path

from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageOps


OLED_ADDRESS = 0x3C
OLED_WIDTH = 128
OLED_HEIGHT = 64
BILD_PFAD = Path(__file__).with_name("shrek.png")


def lade_oled_bild():
    """Schneidet Shreks Kopf und Oberkoerper aus und wandelt sie in 1 Bit um."""
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
    display.display(lade_oled_bild())
    print("Shrek wird auf dem OLED angezeigt")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("Programm beendet")
    finally:
        display.clear()


if __name__ == "__main__":
    main()

