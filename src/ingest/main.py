
"""Zeigt Abstand und CO2-Konzentration auf dem OLED des Raspberry Pi."""

import time
import os

import adafruit_scd4x
from adafruit_extended_bus import ExtendedI2C
from gpiozero import DistanceSensor
from gpiozero.pins.lgpio import LGPIOFactory
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
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
    influx_client = InfluxDBClient(
        url=os.environ["INFLUXDB_URL"],
        token=os.environ["INFLUXDB_TOKEN"],
        org=os.environ["INFLUXDB_ORG"],
        timeout=3000,
    )
    write_api = influx_client.write_api(write_options=SYNCHRONOUS)
    influx_bucket = os.environ["INFLUXDB_BUCKET"]
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
    influx_fehler = False

    try:
        co2_sensor = adafruit_scd4x.SCD4X(ExtendedI2C(1))
        co2_sensor.start_periodic_measurement()
        print("Abstands- und CO2-Sensor gestartet")

        while True:
            abstand_cm = abstandssensor.distance * 100
            neuer_co2_wert = False
            if co2_sensor.data_ready:
                co2_ppm = co2_sensor.CO2
                neuer_co2_wert = True

            co2_text = f"{co2_ppm} ppm" if co2_ppm is not None else "warte..."
            print(f"Abstand: {abstand_cm:.1f} cm | CO2: {co2_text}")
            with canvas(display) as draw:
                draw.text((2, 0), "Abstand", font=beschriftung, fill="white")
                draw.text((2, 11), f"{abstand_cm:.1f} cm", font=wert_schrift, fill="white")
                draw.text((2, 32), "CO2", font=beschriftung, fill="white")
                draw.text((2, 43), co2_text, font=wert_schrift, fill="white")

            punkt = Point("sensorwerte").field("abstand_cm", abstand_cm)
            if neuer_co2_wert:
                punkt.field("co2_ppm", co2_ppm)
            try:
                write_api.write(bucket=influx_bucket, record=punkt)
                if influx_fehler:
                    print("InfluxDB wieder erreichbar")
                influx_fehler = False
            except Exception as fehler:
                if not influx_fehler:
                    print(f"InfluxDB-Schreibfehler: {fehler}")
                influx_fehler = True
            time.sleep(1)
    except KeyboardInterrupt:
        print("Programm beendet")
    finally:
        display.clear()
        abstandssensor.close()
        if co2_sensor is not None:
            co2_sensor.stop_periodic_measurement()
        influx_client.close()


if __name__ == "__main__":
    main()

