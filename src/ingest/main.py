
"""Zeigt Abstand und CO2-Konzentration auf dem OLED des Raspberry Pi."""

import time

import adafruit_scd4x
import board
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
    abstandssensor = DistanceSensor(
        echo=ECHO_GPIO,
        trigger=TRIGGER_GPIO,
        max_distance=4,
        queue_len=5,
        pin_factory=LGPIOFactory(chip=0),
    )
    beschriftung = lade_schriftgroesse(11)
    wert_schrift = lade_schriftgroesse(19)
    co2_ppm = None
    co2_sensor = None

    try:
        co2_sensor = adafruit_scd4x.SCD4X(board.I2C())
        co2_sensor.start_periodic_measurement()
        print("Abstands- und CO2-Sensor gestartet")

        while True:
            abstand_cm = abstandssensor.distance * 100
            if co2_sensor.data_ready:
                co2_ppm = co2_sensor.CO2

            co2_text = f"{co2_ppm} ppm" if co2_ppm is not None else "warte..."
            print(f"Abstand: {abstand_cm:.1f} cm | CO2: {co2_text}")
            with canvas(display) as draw:
                draw.text((2, 0), "Abstand", font=beschriftung, fill="white")
                draw.text((2, 11), f"{abstand_cm:.1f} cm", font=wert_schrift, fill="white")
                draw.text((2, 32), "CO2", font=beschriftung, fill="white")
                draw.text((2, 43), co2_text, font=wert_schrift, fill="white")
            time.sleep(1)
    except KeyboardInterrupt:
        print("Programm beendet")
    finally:
        display.clear()
        abstandssensor.close()
        if co2_sensor is not None:
            co2_sensor.stop_periodic_measurement()


if __name__ == "__main__":
    main()

