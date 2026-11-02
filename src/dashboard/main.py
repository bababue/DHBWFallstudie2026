"""Plain HTML sensor dashboard with live values over one WebSocket."""

import asyncio
import html
import json
import logging
import math
import os
import secrets
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from influxdb_client import InfluxDBClient

from actuators import Actuators

LOG = logging.getLogger("moos.dashboard")


@dataclass(frozen=True)
class Reading:
    side: str
    sensor: str
    field: str
    unit: str
    decimals: int


DISPLAY_ROWS = (
    ("Temperatur", "sht45", "temperature_c", "°C", 1),
    ("Temperatur", "scd40", "temperature_c", "°C", 1),
    ("Luftfeuchte", "sht45", "humidity_pct", "%", 1),
    ("Luftfeuchte", "scd40", "humidity_pct", "%", 1),
    ("Licht", "bh1750", "illuminance_lux", "lx", 0),
    ("CO₂", "scd40", "co2_ppm", "ppm", 0),
)

READINGS = tuple(
    Reading(side, sensor, field, unit, decimals)
    for _, sensor, field, unit, decimals in DISPLAY_ROWS
    for side in ("left", "right")
)


@dataclass(frozen=True)
class Settings:
    url: str
    org: str
    bucket: str
    token: str
    poll_seconds: float
    max_age_seconds: int
    camera_port: int
    actuators_enabled: bool
    control_password: str

    @classmethod
    def from_env(cls):
        settings = cls(
            url=os.getenv("INFLUXDB_URL", "http://influxdb:8086"),
            org=os.getenv("INFLUXDB_ORG", "moos"),
            bucket=os.getenv("INFLUXDB_BUCKET", "moos_sensors"),
            token=os.getenv("INFLUXDB_TOKEN", ""),
            poll_seconds=float(os.getenv("DASHBOARD_POLL_SECONDS", "1")),
            max_age_seconds=int(os.getenv("DASHBOARD_MAX_AGE_SECONDS", "30")),
            camera_port=int(os.getenv("CAMERA_PORT", "8000")),
            actuators_enabled=os.getenv("ACTUATORS_ENABLED", "false").lower() == "true",
            control_password=os.getenv("CONTROL_PASSWORD", ""),
        )
        if not settings.token:
            raise ValueError("INFLUXDB_TOKEN is required")
        if settings.poll_seconds < 1 or settings.max_age_seconds < 5:
            raise ValueError("Dashboard poll interval must be >=1 s and max age >=5 s")
        if not 1 <= settings.camera_port <= 65535:
            raise ValueError("CAMERA_PORT must be 1..65535")
        if settings.actuators_enabled and not settings.control_password:
            raise ValueError("CONTROL_PASSWORD is required when actuators are enabled")
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


def reading_id(reading: Reading) -> str:
    return f"{reading.side}-{reading.sensor}-{reading.field}"


def make_payload(values: dict[tuple[str, str, str], float], error: bool = False,
                 controls: dict[str, int] | None = None) -> dict:
    readings = {}
    for reading in READINGS:
        value = values.get((reading.side, reading.sensor, reading.field))
        if error:
            formatted = "Datenbank nicht erreichbar"
        elif value is None:
            formatted = "kein aktueller Wert"
        else:
            formatted = f"{value:.{reading.decimals}f} {reading.unit}"
        readings[reading_id(reading)] = formatted
    return {"readings": readings, "error": error,
            "controls": controls, "controls_enabled": controls is not None}


def render_page(camera_port: int = 8000) -> str:
    rows = "".join(
        f'<tr><td>{html.escape(label)}</td><td>{sensor.upper()}</td>'
        f'<td id="left-{sensor}-{field}">Verbinde…</td>'
        f'<td id="right-{sensor}-{field}">Verbinde…</td></tr>'
        for label, sensor, field, _, _ in DISPLAY_ROWS
    )
    script = """
<script>
const sliders = {
  led: document.getElementById("led-slider"),
  fan: document.getElementById("fan-slider"),
  pump: document.getElementById("pump-slider")
};
let socket;
let lastControls = null;
const editing = new Set();
function sendControl(device) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  const password = document.getElementById("control-password").value;
  if (!password) {
    document.getElementById("control-status").textContent = "Steuerpasswort eingeben";
    if (lastControls) {
      sliders[device].value = lastControls[device];
      document.getElementById(`${device}-output`).textContent = `${sliders[device].value} %`;
    }
    return;
  }
  socket.send(JSON.stringify({type: "set", device, value: Number(sliders[device].value), password}));
}
for (const [device, slider] of Object.entries(sliders)) {
  slider.addEventListener("input", () => {
    editing.add(device);
    document.getElementById(`${device}-output`).textContent = `${slider.value} %`;
  });
  slider.addEventListener("change", () => {
    sendControl(device);
    editing.delete(device);
  });
}
function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${protocol}//${location.host}/ws`);
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.readings) {
      for (const [id, value] of Object.entries(message.readings)) {
        const cell = document.getElementById(id);
        if (cell) cell.textContent = value;
      }
      for (const [device, slider] of Object.entries(sliders)) {
        slider.disabled = !message.controls_enabled;
        if (message.controls) {
          lastControls = message.controls;
          if (!editing.has(device)) {
            slider.value = message.controls[device];
            document.getElementById(`${device}-output`).textContent = `${slider.value} %`;
          }
        }
      }
      document.getElementById("control-status").textContent =
        message.controls_enabled ? "Steuerung bereit" : "Steuerung deaktiviert";
    }
    if (message.message) {
      document.getElementById("control-status").textContent = message.message;
      if (lastControls) {
        for (const [device, slider] of Object.entries(sliders)) {
          slider.value = lastControls[device];
          document.getElementById(`${device}-output`).textContent = `${slider.value} %`;
        }
      }
    }
  };
  socket.onclose = () => {
    for (const slider of Object.values(sliders)) slider.disabled = true;
    document.getElementById("control-status").textContent = "Verbindung getrennt";
    document.querySelectorAll("tbody td[id]").forEach((cell) => {
      cell.textContent = "Verbindung getrennt";
    });
    setTimeout(connect, 2000);
  };
  socket.onerror = () => socket.close();
}
connect();
const camera = document.getElementById("camera");
function connectCamera() {
  camera.src = `http://${location.hostname}:__CAMERA_PORT__/stream.mjpg?${Date.now()}`;
}
camera.onload = () => { document.getElementById("camera-status").textContent = "Live"; };
camera.onerror = () => {
  document.getElementById("camera-status").textContent = "Kamera nicht erreichbar";
  setTimeout(connectCamera, 2000);
};
connectCamera();
</script>
""".replace("__CAMERA_PORT__", str(camera_port))
    return (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">'
        "<title>Sensorwerte</title></head><body><h1>Sensorwerte</h1>"
        "<table><thead><tr><th>Messwert</th><th>Sensor</th><th>Links</th><th>Rechts</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        '<h2>Kamera</h2><img id="camera" alt="Live-Bild der Kamera" width="640" height="360">'
        '<p id="camera-status">Verbinde…</p>'
        '<h2>Steuerung</h2><label for="control-password">Steuerpasswort</label> '
        '<input id="control-password" type="password" autocomplete="off">'
        '<p id="control-status">Verbinde…</p>'
        '<p><label for="led-slider">Licht</label> '
        '<input id="led-slider" type="range" min="0" max="100" step="5" value="0" disabled> '
        '<output id="led-output">0 %</output></p>'
        '<p><label for="fan-slider">Lüfter</label> '
        '<input id="fan-slider" type="range" min="0" max="100" step="5" value="0" disabled> '
        '<output id="fan-output">0 %</output></p>'
        '<p><label for="pump-slider">Pumpe</label> '
        '<input id="pump-slider" type="range" min="0" max="100" step="5" value="0" disabled> '
        f'<output id="pump-output">0 %</output></p>{script}</body></html>'
    )


class Hub:
    def __init__(self, actuators: Actuators | None = None):
        self.clients: set[WebSocket] = set()
        self.snapshot: dict | None = None
        self.actuators = actuators
        self.values: dict[tuple[str, str, str], float] = {}
        self.error = False

    async def publish_current(self):
        controls = self.actuators.status() if self.actuators is not None else None
        await self.publish(make_payload(self.values, self.error, controls))

    async def update_sensors(self, values: dict[tuple[str, str, str], float], error: bool):
        self.values = values
        self.error = error
        await self.publish_current()

    async def publish(self, payload: dict):
        if payload == self.snapshot:
            return
        self.snapshot = payload
        for client in tuple(self.clients):
            try:
                await asyncio.wait_for(client.send_json(payload), timeout=2)
            except Exception:
                self.clients.discard(client)


async def poll_loop(settings: Settings, hub: Hub):
    while True:
        try:
            values = await asyncio.to_thread(read_latest, settings)
            error = False
        except Exception:
            if hub.snapshot is None or not hub.snapshot["error"]:
                LOG.exception("Could not read current sensor values")
            values = {}
            error = True
        await hub.update_sensors(values, error)
        await asyncio.sleep(settings.poll_seconds)


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = Settings.from_env()
    actuators = None
    if settings.actuators_enabled:
        try:
            import lgpio

            actuators = Actuators(
                lgpio, os.getenv("GPIOCHIP_DEVICE", "/dev/gpiochip0"),
                int(os.getenv("LED_GPIO", "20")), int(os.getenv("FAN_GPIO", "21")),
                int(os.getenv("PUMP_GPIO", "16")),
                int(os.getenv("LED_PWM_HZ", "2000")), int(os.getenv("FAN_PWM_HZ", "5")),
                int(os.getenv("PUMP_PWM_HZ", "5")),
            )
        except Exception:
            LOG.exception("Could not claim LED, fan and pump GPIO pins; controls stay disabled")
    hub = Hub(actuators)
    application.state.hub = hub
    application.state.settings = settings
    task = asyncio.create_task(poll_loop(settings, hub))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        if actuators is not None:
            actuators.close()


app = FastAPI(title="Sensorwerte", lifespan=lifespan)


def _check_control_access(request: Request):
    settings: Settings = request.app.state.settings
    supplied = request.headers.get("x-control-password", "")
    if not settings.control_password or not secrets.compare_digest(supplied, settings.control_password):
        raise HTTPException(status_code=401, detail="Falsches Steuerpasswort")


@app.get("/api/controls")
def control_status(request: Request):
    _check_control_access(request)
    actuators = request.app.state.hub.actuators
    return {"enabled": actuators is not None,
            "values": actuators.status() if actuators is not None else {}}


@app.post("/api/controls")
async def set_control(request: Request):
    _check_control_access(request)
    hub: Hub = request.app.state.hub
    if hub.actuators is None:
        raise HTTPException(status_code=503, detail="Steuerung deaktiviert")
    try:
        command = await request.json()
        if not isinstance(command, dict):
            raise ValueError("Ungültiger Steuerbefehl")
        values = await asyncio.to_thread(hub.actuators.set, command.get("device"), command.get("value"))
    except (ValueError, RuntimeError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    await hub.publish_current()
    return {"enabled": True, "values": values}


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(render_page(Settings.from_env().camera_port))


@app.websocket("/ws")
async def sensor_stream(websocket: WebSocket):
    await websocket.accept()
    hub: Hub = websocket.app.state.hub
    settings: Settings = websocket.app.state.settings
    hub.clients.add(websocket)
    try:
        if hub.snapshot is not None:
            await websocket.send_json(hub.snapshot)
        while True:
            try:
                message = json.loads(await websocket.receive_text())
                if not isinstance(message, dict) or message.get("type") != "set":
                    raise ValueError("Ungültiger Steuerbefehl")
                if hub.actuators is None:
                    raise ValueError("Steuerung deaktiviert")
                password = message.get("password")
                if not isinstance(password, str) or not secrets.compare_digest(password, settings.control_password):
                    raise ValueError("Falsches Steuerpasswort")
                await asyncio.to_thread(hub.actuators.set, message.get("device"), message.get("value"))
                await hub.publish_current()
            except (ValueError, RuntimeError) as error:
                await websocket.send_json({"message": str(error)})
            except WebSocketDisconnect:
                raise
            except Exception:
                LOG.exception("Could not update GPIO output")
                await websocket.send_json({"message": "GPIO-Steuerung fehlgeschlagen"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(websocket)
