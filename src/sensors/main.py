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

from configuration import load
from sensors import BH1750, SCD40, SHT45, SoftwareI2C
from button import ButtonModes, apply_mode_command, start_button_reader
from moss_height import MossAggregate, MossHeight, WaterNoise
from oled import Oled, render, render_mode
from schedule import ScheduledRead
from storage import BufferedWriter
from water_level import WaterLevel


LOG = logging.getLogger("moos.sensors")
STOP = Event()


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
        data = load()
        water = data["wasserstand"]
        moss = tuple(data[f"moos_{index}"] for index in range(1, 5))
        chip = os.getenv("GPIOCHIP_DEVICE", "/dev/gpiochip0")
        token = os.getenv("INFLUXDB_TOKEN", "")
        if not re.fullmatch(r"/dev/gpiochip\d+", chip):
            raise ValueError("GPIOCHIP_DEVICE must be /dev/gpiochipN")
        if not token:
            raise ValueError("INFLUXDB_TOKEN is required")
        config = cls(
            chip=chip,
            left_sda=data["i2c"]["links_sda_gpio"],
            left_scl=data["i2c"]["links_scl_gpio"],
            right_sda=data["i2c"]["rechts_sda_gpio"],
            right_scl=data["i2c"]["rechts_scl_gpio"],
            water_trigger=water["trigger_gpio"],
            water_echo=water["echo_gpio"],
            button_pin=data["taster"]["gpio"],
            water_floor_distance_cm=water["sensor_boden_abstand_cm"],
            moss_pins=tuple((sensor["trigger_gpio"], sensor["echo_gpio"]) for sensor in moss),
            moss_empty_distances_cm=tuple(sensor["bezugsabstand_cm"] for sensor in moss),
            moss_interval=data["messintervalle"]["moos_s"],
            delay_us=data["i2c"]["taktpause_us"],
            sht45_address=data["i2c"]["sht45_adresse"],
            bh1750_address=data["i2c"]["bh1750_adresse"],
            scd40_address=data["i2c"]["scd40_adresse"],
            fast_interval=data["messintervalle"]["schnelle_sensoren_s"],
            co2_poll_interval=data["messintervalle"]["co2_bereitschaft_s"],
            influx_url=os.getenv("INFLUXDB_URL", "http://influxdb:8086"),
            influx_org=os.getenv("INFLUXDB_ORG", "moos"),
            influx_bucket=os.getenv("INFLUXDB_BUCKET", "moos_sensors"),
            influx_token=token,
        )
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
    """Retain each latest field for the dashboard's 12-second window."""
    for key in tuple(values):
        if now - values[key][1] > max_age:
            del values[key]
    if fields:
        values.update({(side, sensor, field): (value, now) for field, value in fields.items()})


def display_readings(values, now, max_age=12):
    return {key: value for key, (value, sampled) in values.items() if now - sampled <= max_age}


def run():
    import lgpio  # Available inside the Raspberry Pi image only.

    # The shared volume survives restarts; do not show its previous mode.
    for path in ('/run/moos/mode.json', '/run/moos/readings.json', '/run/moos/water-safety.json', '/run/moos/mode-command.json'):
        try:
            os.unlink(path)
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
        moss_config = load()
        water_noise = WaterNoise()
        for index, ((trigger, echo), empty_distance) in enumerate(
                zip(config.moss_pins, config.moss_empty_distances_cm), start=1):
            demo = moss_config[f"moos_{index}"]["demo"]
            demo_distance = moss_config[f"moos_{index}"]["demo_abstand_cm"]
            sensor = MossHeight(lgpio, handle, trigger, echo, empty_distance,
                                demo_distance_cm=demo_distance if demo else None,
                                demo_enabled=demo)
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
        published_mode = None
        mode_since = time.time()
        last_command_id = None

        def refresh_display():
            nonlocal next_display, displayed_version, published_mode, mode_since
            mode, show_info, version = modes.snapshot()
            now = time.monotonic()
            if version == displayed_version and now < next_display:
                return
            next_display = now + 1
            if mode != published_mode:
                published_mode = mode
                mode_since = time.time()
            try:
                with open("/run/moos/mode.tmp", "w") as state:
                    json.dump({"mode": mode, "updated": time.time(), "since": mode_since}, state)
                os.replace("/run/moos/mode.tmp", "/run/moos/mode.json")
                wall_now = time.time()
                readings = [dict(side=side, sensor=sensor, field=field, value=value,
                                 sampled=wall_now - (now - sampled))
                            for (side, sensor, field), (value, sampled) in display_values.items()
                            if now - sampled <= 12]
                with open("/run/moos/readings.tmp", "w") as state:
                    json.dump({"updated": wall_now, "readings": readings}, state, allow_nan=False)
                os.replace("/run/moos/readings.tmp", "/run/moos/readings.json")
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
                    last_command_id = apply_mode_command(modes, '/run/moos/mode-command.json',
                                                         last_command_id, time.time())
                    mode, show_info, version = modes.snapshot()
                    due = [task for task in tasks if task.ready(now)]
                    if not due and now < next_display and version == displayed_version:
                        STOP.wait(max(0, min(0.05, next_display - now,
                                             *(task.next_due - now for task in tasks))))
                        continue
                    refresh_display()
                    points = []
                    for task in due:
                        sample_mode = modes.snapshot()[0]
                        side, sensor = task.side, task.sensor
                        is_co2 = isinstance(sensor, SCD40)
                        fields = None
                        error = False
                        try:
                            if isinstance(sensor, MossHeight) and sensor.demo_enabled:
                                sensor.demo_sigma_cm = water_noise.sigma(time.monotonic())
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
                        if sensor is water_sensor:
                            # Publish every attempt, including failures, independently of InfluxDB.
                            try:
                                with open('/run/moos/water-safety.tmp', 'w') as state:
                                    json.dump({'sampled': time.time(), 'distance_cm': fields.get('distance_cm') if fields else None,
                                               'water_level_cm': fields.get('water_level_cm') if fields else None,
                                               'measurement_stable': fields.get('measurement_stable', 0) if fields else 0}, state, allow_nan=False)
                                os.replace('/run/moos/water-safety.tmp', '/run/moos/water-safety.json')
                            except (OSError, ValueError, TypeError) as exc:
                                LOG.warning('Water safety publication failed: %s', exc)
                            if fields and 'distance_cm' in fields:
                                water_noise.add(finished, fields['distance_cm'])
                        task.advance(finished)
                        if is_co2 and side in started and finished - last_co2[side] > 30:
                            LOG.warning("%s/scd40 has no fresh CO2; restarting next poll", side)
                            started.remove(side)
                            error = True
                        # The SCD40 has no new value between its 5 s conversions.
                        # Do not publish a false unhealthy or repeat a stale sample.
                        if not is_co2 or fields is not None or error:
                            update_display_values(display_values, side, sensor.name, fields, finished)
                            timestamp = datetime.now(timezone.utc)
                            points.extend(sample_points(side, sensor.name, fields, timestamp))
                            if isinstance(sensor, MossHeight):
                                aggregate = moss_aggregate.update(
                                    side, fields.get("height_median_1m_cm") if fields else None, finished)
                                points.extend(sample_points("moss", "aggregate", aggregate, timestamp))
                        refresh_display()
                        if modes.snapshot()[0] != sample_mode:
                            break
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
