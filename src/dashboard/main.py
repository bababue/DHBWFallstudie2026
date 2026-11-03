"""Dashboard for the current operating mode and camera."""
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from influxdb_client import InfluxDBClient

from configuration import load, setting
from actuators import Actuators, PumpLocked
from automatic import AutomaticControl, light_schedule
from pump_control import water_overview
from measurements import valid_number, fresh, MAX_DISTANCE_CM, WATER_MAX_AGE_SECONDS, SNAPSHOT_MAX_AGE_SECONDS

from temperature import PERIODS, combine

app = FastAPI(title="Moosbox")
MODE_FILE = Path('/run/moos/mode.json')
MODE_COMMAND_FILE = Path('/run/moos/mode-command.json')
READINGS_FILE = Path('/run/moos/readings.json')
WATER_SAFETY_FILE = Path('/run/moos/water-safety.json')
LOG = logging.getLogger('moos.dashboard')
app.mount('/static', StaticFiles(directory=Path(__file__).parent / 'static'), name='static')


actuators = None
automatic = None


def water_snapshot():
    """A dedicated snapshot includes every attempt, so errors are not hidden by cached display values."""
    try:
        snapshot = json.loads(WATER_SAFETY_FILE.read_text())
        sampled, distance = snapshot['sampled'], snapshot['distance_cm']
        if (not valid_number(sampled) or not fresh(sampled, time.time(), WATER_MAX_AGE_SECONDS)
                or not valid_number(distance) or not 0 < distance <= MAX_DISTANCE_CM):
            return None
        return snapshot
    except (OSError, ValueError, TypeError, KeyError):
        return None


def water_pump_allowed():
    """Fail closed on missing, stale, invalid or high raw water readings."""
    try:
        water = load()['wasserstand']
        snapshot = water_snapshot()
        maximum = water['max_fuellhoehe_cm']
        return bool(snapshot is not None and maximum is not None
                    and water['sensor_boden_abstand_cm'] - snapshot['distance_cm']
                    < maximum)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def pump_state(config):
    result = water_overview(live_readings(), config, time.time())
    snapshot = water_snapshot()
    water = config['wasserstand']
    raw = max(0.0, water['sensor_boden_abstand_cm'] - snapshot['distance_cm']) if snapshot else None
    result.update(water_ready=bool(snapshot and snapshot.get('measurement_stable') == 1
                                  and valid_number(snapshot.get('water_level_cm'))),
                  water_level_cm=snapshot.get('water_level_cm') if snapshot else None,
                  pump_allowed=raw is not None and raw < water['max_fuellhoehe_cm'])
    return result


@app.get('/api/automatic/water')
def automatic_water():
    if automatic is None:
        return Response('Steuerung nicht verfügbar', status_code=503)
    return automatic.status()


@app.post('/api/automatic/pump')
def enable_pump(body: dict):
    if automatic is None:
        return Response('Steuerung nicht verfügbar', status_code=503)
    if type(body.get('enabled')) is not bool:
        return Response('Ungültige Freigabe', status_code=400)
    try:
        return automatic.set_pump_enabled(body['enabled'], body.get('confirmation'))
    except (PermissionError, ValueError) as exc:
        return Response(str(exc), status_code=409)


@app.on_event('startup')
def start_actuators():
    global actuators, automatic
    try:
        import lgpio
        options = load()['aktoren']
        actuators = Actuators(
            lgpio,
            setting('GPIOCHIP_DEVICE', '/dev/gpiochip0'),
            options['licht_gpio'],
            options['luefter_gpio'],
            options['pumpe_gpio'],
            options['licht_pwm_hz'],
            options['luefter_pwm_hz'],
            options['pumpe_pwm_hz'],
            pump_allowed=water_pump_allowed,
        )
        automatic = AutomaticControl(actuators, mode_state, get_water_state=pump_state, get_readings=live_readings)
        automatic.start()
    except Exception:
        LOG.exception('Aktoren konnten nicht initialisiert werden')
        actuators = None


@app.on_event('shutdown')
def stop_actuators():
    global actuators, automatic
    if automatic is not None:
        automatic.close()
        automatic = None
    if actuators is not None:
        actuators.close()
        actuators = None


@app.get('/api/automatic/light')
def automatic_light():
    try:
        return {**light_schedule(), 'thermal': automatic.thermal.state if automatic is not None else None}
    except (OSError, ValueError, TypeError, KeyError):
        LOG.exception('Lichtplan nicht verfügbar')
        return Response('Lichtplan nicht verfügbar', status_code=503)


@app.get('/api/actuators')
def actuator_status():
    if actuators is None:
        return Response('Steuerung nicht verfügbar', status_code=503)
    return actuators.status()


@app.post('/api/actuators/{device}')
def set_actuator(device: str, body: dict):
    if actuators is None or automatic is None:
        return Response('Steuerung nicht verfügbar', status_code=503)
    try:
        return automatic.set_manual(device, body.get('value'))
    except PermissionError:
        return Response('Nur im Manual-Modus verfügbar', status_code=409)
    except PumpLocked as exc:
        return Response(str(exc), status_code=409)
    except ValueError:
        return Response('Ungültiger Stellwert', status_code=400)
    except Exception:
        LOG.exception('Aktoransteuerung fehlgeschlagen')
        return Response('Steuerung fehlgeschlagen', status_code=503)


def mode_state():
    try:
        data = json.loads(MODE_FILE.read_text())
        now = time.time()
        if (data['mode'] in ('AUTO', 'MANUAL') and isinstance(data.get('session'), str)
                and data['session'] and fresh(data.get('updated'), now, SNAPSHOT_MAX_AGE_SECONDS)):
            return data
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return {}


def live_readings():
    """Read the latest unpersisted sensor values shared by the sensor service."""
    try:
        data = json.loads(READINGS_FILE.read_text())
        now = time.time()
        if not fresh(data.get('updated'), now, SNAPSHOT_MAX_AGE_SECONDS):
            return []
        return [r for r in data['readings']
                if isinstance(r, dict) and fresh(r.get('sampled'), now)
                and all(key in r for key in ('side', 'sensor', 'field', 'value'))]
    except (OSError, ValueError, TypeError, KeyError):
        return []


@app.get('/api/debug/sensors')
def debug_sensors():
    return {'readings': live_readings()}


@app.get('/api/temperature')
def temperature(period: str = '1h', current_only: bool = False):
    return metric_data('temperature_c', '°', period, current_only)


@app.get('/api/humidity')
def humidity(period: str = '1h', current_only: bool = False):
    return metric_data('humidity_pct', '%', period, current_only)


@app.get('/api/co2')
def co2(period: str = '1h', current_only: bool = False):
    return metric_data('co2_ppm', 'ppm', period, current_only)


@app.get('/api/light')
def light(period: str = '1h', current_only: bool = False):
    return metric_data('illuminance_lux', 'lx', period, current_only)


@app.get('/api/water')
def water(period: str = '1h', current_only: bool = False):
    return metric_data('water_level_cm', 'cm', period, current_only)


def metric_data(field, unit, period, current_only):
    if period not in PERIODS:
        return Response('Ungültiger Zeitraum', status_code=400)
    duration, window, function = PERIODS[period]
    if field == "co2_ppm" and period == "10m":
        window = "10s"
    bucket = setting('INFLUXDB_BUCKET', 'moos_sensors')
    org = setting('INFLUXDB_ORG', 'moos')
    sensor_filter = 'r.sensor == "bh1750"' if field == 'illuminance_lux' else 'r.sensor == "sht45" or r.sensor == "scd40"'
    if field == 'water_level_cm':
        sensor_filter = 'r.sensor == "ultrasonic"'
    side_filter = 'r.side == "tank"' if field == 'water_level_cm' else 'r.side == "left" or r.side == "right"'
    base = (f'from(bucket: {json.dumps(bucket)})\n'
            '  |> range(start: -DURATION)\n'
            '  |> filter(fn: (r) => r._measurement == "moos_sensor" and '
            f'r._field == {json.dumps(field)} and ({sensor_filter}) '
            f'and ({side_filter}))\n')
    history_query = (base.replace('DURATION', duration) +
                     f'  |> aggregateWindow(every: {window}, fn: {function}, createEmpty: false, timeSrc: "_start")')
    selected_sensors = ({'illuminance_lux': {'bh1750'}, 'water_level_cm': {'ultrasonic'},
                         'co2_ppm': {'scd40'}}.get(field, {'sht45', 'scd40'}))
    selected_sides = {'tank'} if field == 'water_level_cm' else {'left', 'right'}
    current = {(r['side'], r['sensor']): r['value'] for r in live_readings()
               if r['field'] == field and r['sensor'] in selected_sensors and r['side'] in selected_sides}
    if current_only:
        return {'current': combine(current, unit)}
    try:
        with InfluxDBClient(url=setting('INFLUXDB_URL', 'http://influxdb:8086'),
                            token=setting('INFLUXDB_TOKEN', ''), org=org, timeout=5000) as client:
            api = client.query_api()
            windows = {}
            for table in api.query(history_query, org=org):
                for record in table.records:
                    timestamp = int(record.get_time().timestamp())
                    windows.setdefault(timestamp, {})[(record.values.get('side'), record.values.get('sensor'))] = record.get_value()
        points = [{'time': timestamp, **combine(values, unit)} for timestamp, values in sorted(windows.items())]
        return {'current': combine(current, unit), 'points': points, 'window_seconds': int(window[:-1]) * (60 if window.endswith('m') else 1)}
    except Exception:
        LOG.exception('Could not read metric history')
        return Response('Messdaten nicht erreichbar', status_code=503)


@app.get('/api/mode')
def mode():
    return {'mode': mode_state().get('mode')}


@app.post('/api/mode')
def request_mode(body: dict):
    target = body.get('mode')
    if target not in ('AUTO', 'MANUAL'):
        return Response('Ungültiger Modus', status_code=400)
    if not mode_state().get('mode'):
        return Response('Sensorprozess nicht erreichbar', status_code=503)
    if automatic is not None:
        automatic.disable_pump()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=MODE_COMMAND_FILE.parent, delete=False) as output:
            temporary = output.name
            json.dump({'id': uuid.uuid4().hex, 'mode': target, 'requested': time.time()}, output)
        os.replace(temporary, MODE_COMMAND_FILE)
        return {'requested': target}
    except OSError:
        LOG.exception('Moduswechsel konnte nicht angefordert werden')
        return Response('Moduswechsel nicht möglich', status_code=503)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)



@app.get('/', response_class=HTMLResponse)
def index():
    page = (Path(__file__).parent / 'static' / 'index.html').read_text()
    return HTMLResponse(headers={'Cache-Control': 'no-store'}, content=page)


@app.get('/camera/stream.mjpg')
async def camera_stream():
    port = 8000
    client = httpx.AsyncClient(timeout=httpx.Timeout(10, read=None))
    try:
        upstream = await client.send(client.build_request('GET', f'http://camera:{port}/stream.mjpg'), stream=True)
        upstream.raise_for_status()
    except httpx.HTTPError:
        await client.aclose()
        return Response('Kamera nicht erreichbar', status_code=503)

    async def frames():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(frames(), media_type=upstream.headers.get('content-type', 'multipart/x-mixed-replace; boundary=FRAME'), headers={'Cache-Control': 'no-cache, private'})
