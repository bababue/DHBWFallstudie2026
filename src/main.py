
import time

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import ImageFont

# OLED-Konfiguration
OLED_ADDRESS = 0x3C
OLED_WIDTH = 128
OLED_HEIGHT = 64

# Sekunden pro Bildschirm
INTERVAL = 3

# Texte, die nacheinander angezeigt werden
SEITEN = [
    ["Hey team!", "Rezwan ist ein kleiner gooner!"],
    ["OLED Display", "0.96 Zoll", "128 x 64 Pixel"],
    ["Mein Projekt", "Rezwan abfucken"],
    ["GitHub Deployment", "Laeuft!"]
]

# I2C initialisieren
serial = i2c(port=1, address=OLED_ADDRESS)

# Display initialisieren
display = ssd1306(
    serial,
    width=OLED_WIDTH,
    height=OLED_HEIGHT
)

font = ImageFont.load_default()


def zeige_seite(zeilen, nummer):
    """Zeichnet eine Seite auf das OLED."""

    with canvas(display) as draw:

        # Kopfzeile
        draw.text(
            (2, 0),
            "RASPBERRY PI 5",
            font=font,
            fill="white"
        )

        # Trennlinie
        draw.line(
            (0, 14, 127, 14),
            fill="white"
        )

        # Textzeilen
        for index, text in enumerate(zeilen):
            y = 20 + index * 13

            draw.text(
                (4, y),
                text,
                font=font,
                fill="white"
            )

        # Seitenanzeige
        draw.text(
            (105, 55),
            str(nummer),
            font=font,
            fill="white"
        )


def main():
    print("OLED gestartet")

    try:
        while True:
            for index, seite in enumerate(SEITEN, start=1):
                print(f"Seite {index}: {seite}")
                zeige_seite(seite, index)
                time.sleep(INTERVAL)

    except KeyboardInterrupt:
        print("Programm beendet")

    finally:
        display.clear()


if __name__ == "__main__":
    main()

