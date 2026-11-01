"""Plain HTML view of the latest Moos-Pi sensor readings."""

import html
import json
import logging
import math
import os
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from influxdb_client import InfluxDBClient


LOG = logging.getLogger("moos.dashboard")
app = FastAPI(title="Sensorwerte")


@dataclass(frozen=True)
class Reading:
    side: str
    sensor: str
    field: str
    label: str
    unit: str
    decimals: int


READINGS = tuple(
    Reading(side, sensor, field, f"{sensor.upper()} {side_label} – {label}", unit, decimals)
    for side, side_label in (("left", "links"), ("right", "rechts"))
    for sensor, fields in (
        ("sht45", (("temperature_c", "Temperatur", "°C", 1), ("humidity_pct", "Luftfeuchte", "%", 1))),
        ("bh1750", (("illuminance_lux", "Licht", "lx", 0),)),
        ("scd40", (("co2_ppm", "CO₂", "ppm", 0), ("temperature_c", "Temperatur", "°C", 1), ("humidity_pct", "Luftfeuchte", "%", 1))),
    )
    for field, label, unit, decimals in fields
)


@dataclass(frozen=True)
class Settings:
    url: str
    org: str
    bucket: str
    token: str
    refresh_seconds: int
    max_age_seconds: int

    @classmethod
    def from_env(cls):
        settings = cls(
            url=os.getenv("INFLUXDB_URL", "http://influxdb:8086"),
            org=os.getenv("INFLUXDB_ORG", "moos"),
            bucket=os.getenv("INFLUXDB_BUCKET", "moos_sensors"),
            token=os.getenv("INFLUXDB_TOKEN", ""),
            refresh_seconds=int(os.getenv("DASHBOARD_REFRESH_SECONDS", "30")),
            max_age_seconds=int(os.getenv("DASHBOARD_MAX_AGE_SECONDS", "180")),
        )
        if not settings.token:
            raise ValueError("INFLUXDB_TOKEN is required")
        if settings.refresh_seconds < 5 or settings.max_age_seconds < 5:
            raise ValueError("Dashboard refresh and max age must be at least 5 seconds")
        return settings


def read_latest(settings: Settings) -> dict[tuple[str, str, str], float]:
    query = (
        f"from(bucket: {json.dumps(settings.bucket)})\n"
        f"  |> range(start: -{settings.max_age_seconds}s)\n"
        '  |> filter(fn: (r) => r._measurement == "moos_sensor")\n'
        "  |> last()"
    )
    values = {}
    with InfluxDBClient(url=settings.url, token=settings.token, org=settings.org, timeout=5000) as client:
        for table in client.query_api().query(query, org=settings.org):
            for record in table.records:
                key = (record.values.get("side"), record.values.get("sensor"), record.get_field())
                value = float(record.get_value())
                if math.isfinite(value):
                    values[key] = value
    return values


def render_page(values: dict[tuple[str, str, str], float], refresh_seconds: int, error: bool = False) -> str:
    rows = []
    for reading in READINGS:
        value = values.get((reading.side, reading.sensor, reading.field))
        formatted = f"{value:.{reading.decimals}f} {reading.unit}" if value is not None else "kein aktueller Wert"
        rows.append(f"<tr><td>{html.escape(reading.label)}</td><td>{html.escape(formatted)}</td></tr>")
    message = "<p>Datenbank momentan nicht erreichbar.</p>" if error else ""
    return (
        "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
        f'<meta http-equiv="refresh" content="{refresh_seconds}">'
        "<title>Sensorwerte</title></head><body><h1>Sensorwerte</h1>"
        f"{message}<table><thead><tr><th>Sensor</th><th>Aktueller Wert</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )


@app.get("/", response_class=HTMLResponse)
def index():
    settings = Settings.from_env()
    try:
        values = read_latest(settings)
        error = False
    except Exception:
        LOG.exception("Could not read current sensor values")
        values = {}
        error = True
    return HTMLResponse(render_page(values, settings.refresh_seconds, error))
