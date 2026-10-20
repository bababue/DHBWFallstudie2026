
"""Zeigt den neuesten XKCD-Comic auf dem OLED des Raspberry Pi."""

from io import BytesIO
import time

import requests
from gpiozero import PWMOutputDevice
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageOps


OLED_ADDRESS = 0x3C
OLED_WIDTH = 128
OLED_HEIGHT = 64
XKCD_API = "https://xkcd.com/info.0.json"
UPDATE_INTERVAL = 30 * 60
RETRY_INTERVAL = 5 * 60
LAUTSPRECHER_GPIO = 18  # Physischer Pin 12


def lade_aktuellen_comic(session):
    """Laedt den aktuellen Comic und passt ihn an das monochrome OLED an."""
    antwort = session.get(XKCD_API, timeout=15)
    antwort.raise_for_status()
    comic = antwort.json()

    bild_antwort = session.get(comic["img"], timeout=30)
    bild_antwort.raise_for_status()
    with Image.open(BytesIO(bild_antwort.content)) as quelle:
        hintergrund = Image.new("RGBA", quelle.size, "white")
        hintergrund.alpha_composite(quelle.convert("RGBA"))
        skaliert = ImageOps.contain(
            hintergrund.convert("L"), (OLED_WIDTH, OLED_HEIGHT), method=Image.LANCZOS
        )

    flaeche = Image.new("L", (OLED_WIDTH, OLED_HEIGHT), "white")
    flaeche.paste(
        skaliert,
        ((OLED_WIDTH - skaliert.width) // 2, (OLED_HEIGHT - skaliert.height) // 2),
    )
    return comic["num"], ImageOps.invert(flaeche).convert("1")


def main():
    lautsprecher = PWMOutputDevice(LAUTSPRECHER_GPIO, frequency=440)
    try:
        lautsprecher.value = 0.5
        time.sleep(1)
    finally:
        lautsprecher.off()
        lautsprecher.close()

    serial = i2c(port=1, address=OLED_ADDRESS)
    display = ssd1306(serial, width=OLED_WIDTH, height=OLED_HEIGHT)
    letzter_comic = None

    try:
        with requests.Session() as session:
            while True:
                try:
                    nummer, bild = lade_aktuellen_comic(session)
                    if nummer != letzter_comic:
                        display.display(bild)
                        letzter_comic = nummer
                        print(f"XKCD-Comic {nummer} wird angezeigt")
                    time.sleep(UPDATE_INTERVAL)
                except (requests.RequestException, OSError, ValueError, KeyError) as fehler:
                    print(f"XKCD konnte nicht geladen werden: {fehler}")
                    time.sleep(RETRY_INTERVAL)
    except KeyboardInterrupt:
        print("Programm beendet")
    finally:
        display.clear()


if __name__ == "__main__":
    main()

