"""Read the I2C and water-level sensors and write samples to InfluxDB 2."""

import logging
import json
import os
import re
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from configuration import setting, load
from sensors import BH1750, SCD40, SHT45, SoftwareI2C
from button import ButtonModes, start_button_reader
from moss_height import MossAggregate, MossHeight
from oled import Oled, render, render_mode
from schedule import ScheduledRead
from storage import BufferedWriter
from water_level import WaterLevel


LOG = logging.getLogger("moos.sensors")
STOP = Event()


def env_int(name: str, default: str) -> int:
    return int(setting(name, default), 0)


@dataclass(frozen=True)
class Config:
    chip: str
    left_sda: int
    left_scl: int
    right_sda: int
    right_scl: int
    water_trigger: int
    water_echo: int
    button_pin: int
    water_floor_distance_cm: float
    moss_pins: tuple[tuple[int, int], ...]
    moss_empty_distances_cm: tuple[float | None, ...]
    moss_interval: float
    delay_us: int
    sht45_address: int
    bh1750_address: int
    scd40_address: int
    fast_interval: float
    co2_poll_interval: float
    influx_url: str
    influx_org: str
    influx_bucket: str
    influx_token: str

    @classmethod
    def from_config(cls):
        config = cls(
            chip=setting("GPIOCHIP_DEVICE", "/dev/gpiochip0"),
            left_sda=env_int("LEFT_I2C_SDA_GPIO", "15"),
            left_scl=env_int("LEFT_I2C_SCL_GPIO", "14"),
            right_sda=env_int("RIGHT_I2C_SDA_GPIO", "23"),
            right_scl=env_int("RIGHT_I2C_SCL_GPIO", "24"),
            water_trigger=env_int("WATER_TRIGGER_GPIO", "6"),
            water_echo=env_int("WATER_ECHO_GPIO", "13"),
            button_pin=env_int("BUTTON_GPIO", "26"),
            water_floor_distance_cm=float(setting("WATER_FLOOR_DISTANCE_CM", "8.62")),
            moss_pins=tuple((env_int(f"MOSS_{index}_TRIGGER_GPIO", str(trigger)),
                             env_int(f"MOSS_{index}_ECHO_GPIO", str(echo)))
                            for index, (trigger, echo) in enumerate(
                                ((9, 11), (0, 5), (22, 10), (17, 27)), start=1)),
            moss_empty_distances_cm=tuple(
                float(value) if (value := setting(f"MOSS_{index}_EMPTY_DISTANCE_CM", "")) else None
                for index in range(1, 5)),
            moss_interval=float(setting("MOSS_SAMPLE_INTERVAL_SECONDS", "4")),
            delay_us=env_int("I2C_DELAY_US", "12"),
            sht45_address=env_int("SHT45_ADDRESS", "0x44"),
            bh1750_address=env_int("BH1750_ADDRESS", "0x23"),
            scd40_address=env_int("SCD40_ADDRESS", "0x62"),
            fast_interval=float(setting("FAST_SAMPLE_INTERVAL_SECONDS", "1")),
            co2_poll_interval=float(setting("CO2_READY_POLL_SECONDS", "0.5")),
            influx_url=setting("INFLUXDB_URL", "http://influxdb:8086"),
            influx_org=setting("INFLUXDB_ORG", "moos"),
            influx_bucket=setting("INFLUXDB_BUCKET", "moos_sensors"),
            influx_token=setting("INFLUXDB_TOKEN", ""),
        )
        pins = (config.left_sda, config.left_scl, config.right_sda, config.right_scl,
                config.water_trigger, config.water_echo, config.button_pin,
                *(pin for pair in config.moss_pins for pin in pair))
        if len(set(pins)) != len(pins) or not all(0 <= pin <= 27 for pin in pins):
            raise ValueError("Sensor GPIO pins must be distinct BCM numbers 0..27")
        if not 0 < config.water_floor_distance_cm <= WaterLevel.MAX_DISTANCE_CM:
            raise ValueError("WATER_FLOOR_DISTANCE_CM must be within the sensor range")
        if not 4 <= config.moss_interval <= 60:
            raise ValueError("MOSS_SAMPLE_INTERVAL_SECONDS must be 4..60")
        if any(distance is not None and not 0 < distance <= MossHeight.MAX_DISTANCE_CM
               for distance in config.moss_empty_distances_cm):
            raise ValueError("MOSS_N_EMPTY_DISTANCE_CM must be within the sensor range")
        if not re.fullmatch(r"/dev/gpiochip\d+", config.chip):
            raise ValueError("GPIOCHIP_DEVICE must be /dev/gpiochipN")
        if not 0.5 <= config.fast_interval <= 60:
            raise ValueError("FAST_SAMPLE_INTERVAL_SECONDS must be 0.5..60")
        if not 0.2 <= config.co2_poll_interval <= 5:
            raise ValueError("CO2_READY_POLL_SECONDS must be 0.2..5")
        if config.delay_us < 5:
            raise ValueError("I2C_DELAY_US must be >=5")
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


def update_display_values(values, side, sensor, fields, now, max_age=12):
    """Keep only recent fields; failed reads clear that sensor immediately."""
    for key in tuple(values):
        if key[:2] == (side, sensor) or now - values[key][1] > max_age:
            del values[key]
    if fields:
        values.update({(side, sensor, field): (value, now) for field, value in fields.items()})


def display_readings(values, now, max_age=12):
    return {key: value for key, (value, sampled) in values.items() if now - sampled <= max_age}


def run():
    import lgpio  # Available inside the Raspberry Pi image only.

    # The shared volume survives restarts; do not show its previous mode.
    try:
        os.unlink('/run/moos/mode.json')
    except FileNotFoundError:
        pass

    config = Config.from_config()
    from configuration import revision
    loaded_revision = revision()
    chip_number = int(config.chip.removeprefix("/dev/gpiochip"))
    handle = lgpio.gpiochip_open(chip_number)
    buses = []
    scd_sensors = []
    water_sensor = None
    moss_sensors = []
    oled = None
    button_thread = None
    button_claimed = False
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
                                  config.water_floor_distance_cm, options=load()["wasserstand"])
        sensors.append(("tank", water_sensor))
        for index, ((trigger, echo), empty_distance) in enumerate(
                zip(config.moss_pins, config.moss_empty_distances_cm), start=1):
            sensor = MossHeight(lgpio, handle, trigger, echo, empty_distance)
            moss_sensors.append(sensor)
            sensors.append((f"moss{index}", sensor))
        oled = Oled(buses[0])
        modes = ButtonModes()
        button_thread = start_button_reader(lgpio, handle, config.button_pin, STOP, modes)
        button_claimed = True
        start_time = time.monotonic()
        tasks = []
        for side, sensor in sensors:
            if isinstance(sensor, MossHeight):
                interval = config.moss_interval
                first_due = start_time + (int(side[-1]) - 1) * interval / 4
            else:
                interval = config.co2_poll_interval if isinstance(sensor, SCD40) else config.fast_interval
                first_due = start_time
            tasks.append(ScheduledRead(side, sensor, interval, first_due))
        moss_aggregate = MossAggregate()
        started = set()
        last_co2 = {}
        display_values = {}
        next_display = start_time
        displayed_version = None
        maintenance_active = False
        next_stop_attempt = 0.0

        def refresh_display():
            nonlocal next_display, displayed_version
            mode, show_info, version = modes.snapshot()
            now = time.monotonic()
            if version == displayed_version and now < next_display:
                return
            next_display = now + 1
            try:
                with open("/run/moos/mode.tmp", "w") as state:
                    json.dump({"mode": mode, "updated": time.time()}, state)
                os.replace("/run/moos/mode.tmp", "/run/moos/mode.json")
            except OSError as exc:
                LOG.warning("Mode publication failed: %s", exc)
            try:
                frame = (render(display_readings(display_values, now))
                         if show_info else render_mode(mode))
                oled.zeigen(frame)
                displayed_version = version
            except Exception as exc:
                LOG.warning("OLED update failed: %s", exc)

        with InfluxDBClient(url=config.influx_url, token=config.influx_token, org=config.influx_org, timeout=5000) as client:
            writer = client.write_api(write_options=SYNCHRONOUS)
            buffered = BufferedWriter(
                lambda points: writer.write(bucket=config.influx_bucket, org=config.influx_org,
                                            record=points), STOP)
            try:
                while not STOP.is_set():
                    if revision() != loaded_revision:
                        LOG.info("Configuration changed; restarting sensor service")
                        break
                    now = time.monotonic()
                    mode, show_info, version = modes.snapshot()
                    if mode == "MAINTENANCE":
                        if not maintenance_active:
                            maintenance_active = True
                            display_values.clear()
                            water_sensor.recent.clear()
                            water_sensor.last_sample = None
                            for sensor in moss_sensors:
                                sensor.recent_distances.clear()
                            moss_aggregate.latest.clear()
                            LOG.info("Maintenance: measurements paused")
                        if started and now >= next_stop_attempt:
                            next_stop_attempt = now + 2
                            for side, sensor in zip(("left", "right"), scd_sensors):
                                if side in started:
                                    try:
                                        sensor.stop()
                                        started.remove(side)
                                    except (OSError, ValueError, lgpio.error) as exc:
                                        LOG.warning("%s/scd40 stop failed: %s", side, exc)
                        refresh_display()
                        STOP.wait(0.05)
                        continue
                    if maintenance_active:
                        maintenance_active = False
                        # Restart every SCD40, including a sensor whose stop failed.
                        started.clear()
                        last_co2.clear()
                        for task in tasks:
                            task.next_due = now + ((int(task.side[-1]) - 1) * task.interval / 4
                                                   if isinstance(task.sensor, MossHeight) else 0)
                        LOG.info("Maintenance ended: measurements resumed")
                    due = [task for task in tasks if task.ready(now)]
                    if not due and now < next_display and version == displayed_version:
                        STOP.wait(max(0, min(0.05, next_display - now,
                                             *(task.next_due - now for task in tasks))))
                        continue
                    refresh_display()
                    points = []
                    for task in due:
                        if modes.snapshot()[0] == "MAINTENANCE":
                            break
                        side, sensor = task.side, task.sensor
                        is_co2 = isinstance(sensor, SCD40)
                        fields = None
                        error = False
                        try:
                            if is_co2 and side not in started:
                                sensor.start()
                                started.add(side)
                                last_co2[side] = time.monotonic()
                            else:
                                fields = sensor.read()
                            if fields is not None:
                                LOG.info("%s/%s %s", side, sensor.name, fields)
                                if is_co2:
                                    last_co2[side] = time.monotonic()
                        except (OSError, ValueError, lgpio.error) as exc:
                            LOG.warning("%s/%s read failed: %s", side, sensor.name, exc)
                            error = True
                        finished = time.monotonic()
                        task.advance(finished)
                        if is_co2 and side in started and finished - last_co2[side] > 30:
                            LOG.warning("%s/scd40 has no fresh CO2; restarting next poll", side)
                            started.remove(side)
                            error = True
                        if side in ("left", "right") and (not is_co2 or fields is not None or error):
                            update_display_values(display_values, side, sensor.name, fields, finished)
                        # The SCD40 has no new value between its 5 s conversions.
                        # Do not publish a false unhealthy or repeat a stale sample.
                        if not is_co2 or fields is not None or error:
                            timestamp = datetime.now(timezone.utc)
                            points.extend(sample_points(side, sensor.name, fields, timestamp))
                            if isinstance(sensor, MossHeight):
                                aggregate = moss_aggregate.update(
                                    side, fields.get("height_median_1m_cm") if fields else None, finished)
                                points.extend(sample_points("moss", "aggregate", aggregate, timestamp))
                        refresh_display()
                    buffered.submit(points)
            finally:
                STOP.set()
                buffered.close()
    finally:
        STOP.set()
        if button_thread is not None:
            button_thread.join(timeout=1)
        if button_claimed:
            try:
                lgpio.gpio_free(handle, config.button_pin)
            except Exception:
                LOG.exception("Could not release button pin")
        if oled is not None:
            try:
                oled.ausschalten()
            except Exception as exc:
                LOG.warning("OLED shutdown failed: %s", exc)
        for sensor in scd_sensors:
            try:
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
        for sensor in reversed(moss_sensors):
            try:
                sensor.close()
            except Exception:
                LOG.exception("Could not release moss height sensor pins")
        lgpio.gpiochip_close(handle)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    run()
