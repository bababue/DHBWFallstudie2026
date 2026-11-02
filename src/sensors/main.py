"""Read the I2C and water-level sensors and write samples to InfluxDB 2."""

import logging
import os
import re
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Lock, Thread

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from sensors import BH1750, SCD40, SHT45, SoftwareI2C
from display_runtime import run_display
from water_level import WaterLevel


LOG = logging.getLogger("moos.sensors")
STOP = Event()


def env_int(name: str, default: str) -> int:
    return int(os.getenv(name, default), 0)


@dataclass(frozen=True)
class Config:
    chip: str
    left_sda: int
    left_scl: int
    right_sda: int
    right_scl: int
    water_trigger: int
    water_echo: int
    water_floor_distance_cm: float
    delay_us: int
    sht45_address: int
    bh1750_address: int
    scd40_address: int
    interval: float
    influx_url: str
    influx_org: str
    influx_bucket: str
    influx_token: str

    @classmethod
    def from_env(cls):
        if os.getenv("B24_1_ENABLED", "false").lower() == "true":
            raise ValueError("B24_1 reading is not implemented; leave B24_1_ENABLED=false")
        config = cls(
            chip=os.getenv("GPIOCHIP_DEVICE", "/dev/gpiochip0"),
            left_sda=env_int("LEFT_I2C_SDA_GPIO", "15"),
            left_scl=env_int("LEFT_I2C_SCL_GPIO", "14"),
            right_sda=env_int("RIGHT_I2C_SDA_GPIO", "23"),
            right_scl=env_int("RIGHT_I2C_SCL_GPIO", "24"),
            water_trigger=env_int("WATER_TRIGGER_GPIO", "6"),
            water_echo=env_int("WATER_ECHO_GPIO", "13"),
            water_floor_distance_cm=float(os.getenv("WATER_FLOOR_DISTANCE_CM", "8.62")),
            delay_us=env_int("I2C_DELAY_US", "12"),
            sht45_address=env_int("SHT45_ADDRESS", "0x44"),
            bh1750_address=env_int("BH1750_ADDRESS", "0x23"),
            scd40_address=env_int("SCD40_ADDRESS", "0x62"),
            interval=float(os.getenv("SAMPLE_INTERVAL_SECONDS", "6")),
            influx_url=os.getenv("INFLUXDB_URL", "http://influxdb:8086"),
            influx_org=os.getenv("INFLUXDB_ORG", "moos"),
            influx_bucket=os.getenv("INFLUXDB_BUCKET", "moos_sensors"),
            influx_token=os.getenv("INFLUXDB_TOKEN", ""),
        )
        pins = (config.left_sda, config.left_scl, config.right_sda, config.right_scl,
                config.water_trigger, config.water_echo)
        if len(set(pins)) != len(pins) or not all(0 <= pin <= 27 for pin in pins):
            raise ValueError("Sensor GPIO pins must be distinct BCM numbers 0..27")
        if not 0 < config.water_floor_distance_cm <= WaterLevel.MAX_DISTANCE_CM:
            raise ValueError("WATER_FLOOR_DISTANCE_CM must be within the sensor range")
        if not re.fullmatch(r"/dev/gpiochip\d+", config.chip):
            raise ValueError("GPIOCHIP_DEVICE must be /dev/gpiochipN")
        if config.interval < 6 or config.delay_us < 5:
            raise ValueError("Sampling interval must be >=6 s and I2C_DELAY_US >=5")
        if not all(0x03 <= a <= 0x77 for a in (config.sht45_address, config.bh1750_address, config.scd40_address)):
            raise ValueError("I2C addresses must be 7-bit addresses")
        if not config.influx_token:
            raise ValueError("INFLUXDB_TOKEN is required")
        return config


def sample_points(side: str, sensor_name: str, fields: dict[str, float] | None, timestamp: datetime):
    health = Point("moos_sensor_health").tag("side", side).tag("sensor", sensor_name).field("healthy", 1 if fields else 0).time(timestamp, WritePrecision.NS)
    points = [health]
    if fields:
        measurement = Point("moos_sensor").tag("side", side).tag("sensor", sensor_name).time(timestamp, WritePrecision.NS)
        for name, value in fields.items():
            measurement.field(name, value)
        points.append(measurement)
    return points


def run():
    import lgpio  # Available inside the Raspberry Pi image only.

    config = Config.from_env()
    chip_number = int(config.chip.removeprefix("/dev/gpiochip"))
    handle = lgpio.gpiochip_open(chip_number)
    buses = []
    scd_sensors = []
    water_sensor = None
    bus_lock = Lock()
    readings_lock = Lock()
    readings = {}
    display_thread = None
    try:
        for side, sda, scl in (
            ("left", config.left_sda, config.left_scl),
            ("right", config.right_sda, config.right_scl),
        ):
            bus = SoftwareI2C(lgpio, handle, sda, scl, config.delay_us)
            buses.append(bus)
            scd_sensors.append(SCD40(bus, config.scd40_address))
        sensors = [
            (side, sensor)
            for side, bus, scd in zip(("left", "right"), buses, scd_sensors)
            for sensor in (SHT45(bus, config.sht45_address), BH1750(bus, config.bh1750_address), scd)
        ]
        water_sensor = WaterLevel(lgpio, handle, config.water_trigger, config.water_echo,
                                  config.water_floor_distance_cm)
        sensors.append(("tank", water_sensor))
        if os.getenv("OLED_ENABLED", "true").lower() == "true":
            display_thread = Thread(
                target=run_display,
                args=(buses[0], bus_lock, readings, readings_lock, STOP),
                daemon=True,
            )
            display_thread.start()
        started = set()
        last_co2 = {}
        with InfluxDBClient(url=config.influx_url, token=config.influx_token, org=config.influx_org, timeout=10000) as client:
            writer = client.write_api(write_options=SYNCHRONOUS)
            pending = []
            while not STOP.is_set():
                cycle_start = time.monotonic()
                points = []
                for side, sensor in sensors:
                    timestamp = datetime.now(timezone.utc)
                    try:
                        with bus_lock:
                            if isinstance(sensor, SCD40) and side not in started:
                                sensor.start()
                                started.add(side)
                                last_co2[side] = time.monotonic()
                                fields = None  # First CO2 value takes about five seconds.
                            else:
                                fields = sensor.read()
                                if isinstance(sensor, SCD40) and fields is not None:
                                    last_co2[side] = time.monotonic()
                        if fields is not None:
                            LOG.info("%s/%s %s", side, sensor.name, fields)
                    except (OSError, ValueError, lgpio.error) as error:
                        LOG.warning("%s/%s read failed: %s", side, sensor.name, error)
                        fields = None
                    with readings_lock:
                        if fields is None:
                            for key in [key for key in readings if key[:2] == (side, sensor.name)]:
                                del readings[key]
                        else:
                            readings.update({(side, sensor.name, name): value
                                             for name, value in fields.items()})
                    if isinstance(sensor, SCD40) and side in started:
                        if time.monotonic() - last_co2[side] > max(30, 2 * config.interval):
                            LOG.warning("%s/scd40 has no fresh CO2; restarting next cycle", side)
                            started.remove(side)
                    points.extend(sample_points(side, sensor.name, fields, timestamp))
                pending.extend(points)
                try:
                    writer.write(bucket=config.influx_bucket, org=config.influx_org, record=pending)
                    pending.clear()
                except Exception as error:
                    LOG.warning("InfluxDB write failed; retaining %d points: %s", len(pending), error)
                    if len(pending) > 2000:
                        pending = pending[-2000:]
                        LOG.error("InfluxDB backlog exceeded 2000 points; oldest samples dropped")
                STOP.wait(max(0, config.interval - (time.monotonic() - cycle_start)))
    finally:
        STOP.set()
        if display_thread is not None:
            display_thread.join(timeout=3)
        for sensor in scd_sensors:
            try:
                with bus_lock:
                    sensor.stop()
            except Exception:
                pass
        for bus in reversed(buses):
            try:
                bus.close()
            except Exception:
                LOG.exception("Could not release I2C pins")
        if water_sensor is not None:
            try:
                water_sensor.close()
            except Exception:
                LOG.exception("Could not release water level sensor pins")
        lgpio.gpiochip_close(handle)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    run()
