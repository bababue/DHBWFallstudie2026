"""Dashboard for the current operating mode and camera."""
import json
import html
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from influxdb_client import InfluxDBClient

from configuration import load, setting
from actuators import Actuators, PumpLocked
from automatic import AutomaticControl, light_schedule
from pump_control import water_overview, valid_number

from temperature import PERIODS, combine

app = FastAPI(title="Moosbox")
MODE_FILE = Path('/run/moos/mode.json')
MODE_COMMAND_FILE = Path('/run/moos/mode-command.json')
READINGS_FILE = Path('/run/moos/readings.json')
WATER_SAFETY_FILE = Path('/run/moos/water-safety.json')
LOG = logging.getLogger('moos.dashboard')


actuators = None
automatic = None


def water_snapshot():
    """A dedicated snapshot includes every attempt, so errors are not hidden by cached display values."""
    try:
        snapshot = json.loads(WATER_SAFETY_FILE.read_text())
        sampled, distance = snapshot['sampled'], snapshot['distance_cm']
        if (not valid_number(sampled) or not 0 <= time.time() - sampled <= 3
                or not valid_number(distance) or not 0 < distance <= 400):
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
                    < maximum - water['sicherheitsabstand_cm'])
    except (OSError, ValueError, TypeError, KeyError):
        return False


def pump_state():
    config = load()
    result = water_overview(live_readings(), config, time.time())
    snapshot = water_snapshot()
    water = config['wasserstand']
    result.update({'water_ready': bool(snapshot and snapshot.get('measurement_stable') == 1
                                      and valid_number(snapshot.get('water_level_cm'))),
                   'water_level_cm': snapshot.get('water_level_cm') if snapshot else None,
                   'raw_level_cm': max(0, water['sensor_boden_abstand_cm'] - snapshot['distance_cm']) if snapshot else None,
                   'pump_allowed': water_pump_allowed(),
                   'target_ceiling_cm': (max(0, water['max_fuellhoehe_cm'] - water['sicherheitsabstand_cm']
                                            - config['automatik']['pumpe_hysterese_cm'])
                                         if water['max_fuellhoehe_cm'] is not None else None)})
    return result, config['automatik']


@app.get('/api/automatic/water')
def automatic_water():
    try:
        state, _ = pump_state()
        state['reason'] = automatic.pump.reason if automatic is not None and mode_state().get('mode') == 'AUTO' else ''
        return state
    except (OSError, ValueError, TypeError, KeyError):
        LOG.exception('Wasserregelung nicht verfügbar')
        return Response('Wasserregelung nicht verfügbar', status_code=503)


@app.on_event('startup')
def start_actuators():
    global actuators, automatic
    try:
        import lgpio
        actuators = Actuators(lgpio, setting('GPIOCHIP_DEVICE', '/dev/gpiochip0'),
                              int(setting('LED_GPIO')), int(setting('FAN_GPIO')), int(setting('PUMP_GPIO')),
                              int(setting('LED_PWM_HZ')), int(setting('FAN_PWM_HZ')), int(setting('PUMP_PWM_HZ')),
                              pump_allowed=water_pump_allowed)
        automatic = AutomaticControl(actuators, lambda: mode_state().get('mode'), get_water_state=pump_state, get_readings=live_readings)
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
        if data['mode'] in ('AUTO', 'MANUAL', 'MEASURING') and 0 <= now - data['updated'] < 5:
            return data
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return {}


def live_readings():
    """Read the latest unpersisted sensor values shared by the sensor service."""
    try:
        data = json.loads(READINGS_FILE.read_text())
        now = time.time()
        if not 0 <= now - data['updated'] <= 5:
            return []
        return [r for r in data['readings']
                if isinstance(r, dict) and isinstance(r.get('sampled'), (int, float))
                and 0 <= now - r['sampled'] <= 12
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
        LOG.exception('Could not read temperature')
        return Response('Temperaturdaten nicht erreichbar', status_code=503)


@app.get('/api/moss')
def moss(period: str = '1h', current_only: bool = False):
    if period not in PERIODS:
        return Response('Ungültiger Zeitraum', status_code=400)
    duration, window, function = PERIODS[period]
    # Each sensor reports about every four seconds.
    if period == '10m':
        window = '10s'
    org = setting('INFLUXDB_ORG', 'moos')
    base = (f'from(bucket: {json.dumps(setting("INFLUXDB_BUCKET", "moos_sensors"))})\n'
            '  |> range(start: -DURATION)\n'
            '  |> filter(fn: (r) => r._measurement == "moos_sensor" and r.sensor == "ultrasonic" '
            'and r._field == "height_median_1m_cm" and (r.side == "moss1" or r.side == "moss2" or r.side == "moss3" or r.side == "moss4"))\n')
    current = {r['side']: r['value'] for r in live_readings()
               if r['sensor'] == 'ultrasonic' and r['field'] == 'height_cm'
               and r['side'] in {f'moss{index}' for index in range(1, 5)}}
    if current_only:
        return {'current': current}
    try:
        with InfluxDBClient(url=setting('INFLUXDB_URL', 'http://influxdb:8086'),
                            token=setting('INFLUXDB_TOKEN', ''), org=org, timeout=5000) as client:
            api = client.query_api()
            series = {f'moss{index}': [] for index in range(1, 5)}
            query = base.replace('DURATION', duration) + f'  |> aggregateWindow(every: {window}, fn: {function}, createEmpty: false, timeSrc: "_start")'
            for table in api.query(query, org=org):
                for record in table.records:
                    side = record.values.get('side')
                    if side in series:
                        series[side].append({'time': int(record.get_time().timestamp()), 'value': record.get_value()})
            for points in series.values():
                points.sort(key=lambda point: point['time'])
        return {'current': current, 'series': series, 'window_seconds': int(window[:-1]) * (60 if window.endswith('m') else 1)}
    except Exception:
        LOG.exception('Could not read moss heights')
        return Response('Moosdaten nicht erreichbar', status_code=503)


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
    page = '''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Moosbox</title><link rel="stylesheet" href="https://rsms.me/inter/inter.css"><style>
:root{--page:#fff;--bar:#fff;--text:#000;--muted:#000;--border:#d4d4d4;--grid:#e5e5e5;--accent:#404040;--dark:#171717;--backdrop:#00000066;--mode-color:#15803d}
:root[data-mode="MANUAL"]{--mode-color:#1d4ed8}
:root[data-mode="MEASURING"]{--mode-color:#a16207}

    *{box-sizing:border-box}html{background:#fff;color-scheme:light}body{min-height:100vh;margin:0;background:#fff;color:var(--text);font:16px "Inter",system-ui,sans-serif}main{background:#fff;min-height:100vh;width:100%;padding:clamp(16px,2vw,32px);padding-top:calc(var(--topbar-height,100px) + 24px)}header{margin-bottom:24px}.topbar{position:fixed;top:0;left:0;right:0;z-index:10;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:16px clamp(16px,2vw,32px);background:#fff;backdrop-filter:blur(12px);border-bottom:1px solid var(--border)}.mode-block{display:flex;align-items:center;gap:18px}.mode-switch{position:relative;display:inline-flex;align-items:center;flex-shrink:0}.mode-switch input{position:absolute;opacity:0;width:1px;height:1px}.mode-slider{width:66px;height:38px;border-radius:999px;background:#bdbdbd;cursor:pointer;transition:background .15s}.mode-slider::before{content:"";display:block;width:30px;height:30px;margin:4px;border-radius:50%;background:#fff;transition:transform .15s}.mode-switch input:checked + .mode-slider{background:#333}.mode-switch input:checked + .mode-slider::before{transform:translateX(28px)}.mode-switch input:focus-visible + .mode-slider{outline:2px solid #111;outline-offset:3px}.mode-switch input:disabled + .mode-slider{opacity:.45;cursor:default}.topbar h1{color:#000;font-size:clamp(1.5rem,3vw,2.4rem);margin:0;line-height:1.2}.topbar .toolbar{margin:0;justify-content:flex-end}.metric-readout{display:flex;align-items:center;gap:clamp(16px,3vw,40px);margin:8px 0 20px}.metric-readout .status{margin:0;line-height:1.4}.metric-readout p{font-variant-numeric:tabular-nums}header p,.label{color:var(--muted);font-size:.8rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase}h1{font-size:clamp(2rem,5vw,3.5rem);margin:.25em 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.actuator-panel{display:grid;grid-template-columns:1fr;align-content:center;gap:24px}.actuator-panel[hidden]{display:none}#manual-actuators{display:grid;gap:24px}#manual-actuators[hidden],#auto-actuators[hidden]{display:none}.actuator-control label{display:flex;justify-content:space-between;margin-bottom:12px}.actuator-control input{width:100%;accent-color:#404040}.actuator-error{grid-column:1/-1;margin:0}.auto-values{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.auto-values span{display:block}.auto-values strong{display:block;font-size:clamp(1.4rem,2.5vw,2rem);margin-top:8px}.auto-timeline{margin-top:28px}.auto-timeline-head{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}.auto-timeline-bar{height:10px;border-radius:8px;background:#e5e5e5;position:relative;margin:18px 0 8px}.auto-light-segment{position:absolute;top:0;bottom:0;background:#bca343;border-radius:8px}.auto-now{position:absolute;top:-4px;width:3px;height:18px;background:#171717;transform:translateX(-50%)}.auto-ticks{display:flex;justify-content:space-between;font-size:.8rem}.water-panel{grid-column:1/-1}.water-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px;margin:24px 0}.water-metric-label{display:flex;align-items:center;gap:8px}.water-metric-label i{display:inline-block;width:20px;border-top:2px solid}.legend-target{color:#2563eb;border-top-style:dashed!important}.overview-row{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:20px}.card{background:transparent;border:0;border-radius:0;padding:24px;min-width:0}.mode{display:flex;flex-direction:column;justify-content:space-between;min-height:310px}.mode strong{font-size:clamp(2rem,4vw,3.5rem);overflow-wrap:anywhere}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--accent);margin-right:8px}#debug-panel{grid-column:1/-1}.camera img{display:block;width:100%;aspect-ratio:16/9;object-fit:contain;background:var(--dark);border-radius:12px}.status:empty{display:none}.status{color:var(--muted);font-size:.9rem}#temperature-source,#humidity-source,#co2-source,#light-source,#water-source,#moss-source{white-space:pre-line}.temperature-head,.humidity-head,.co2-head,.light-head,.water-head,.moss-head{display:flex;justify-content:space-between;align-items:start;gap:16px;flex-wrap:wrap}.temperature-value,.humidity-value,.co2-value,.light-value,.water-value,.moss-value{font-size:clamp(2rem,3.5vw,2.8rem);font-weight:700;margin:0}select{appearance:none;-webkit-appearance:none;border:1px solid var(--border);border-radius:8px;background-color:white;background-image:url("data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2212%22%20height%3D%228%22%20viewBox%3D%220%200%2012%208%22%3E%3Cpath%20d%3D%22m1%201%205%205%205-5%22%20fill%3D%22none%22%20stroke%3D%22%23000000%22%20stroke-width%3D%221.5%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%2F%3E%3C%2Fsvg%3E");background-repeat:no-repeat;background-position:right 14px center;background-size:12px 8px;padding:10px 40px 10px 14px;color:var(--text);font:inherit;line-height:1.3;cursor:pointer}.chart-legend{display:flex;gap:20px;font-size:.8rem}.chart-legend i{display:inline-block;width:20px;border-top:2px solid;vertical-align:middle;margin-right:6px}.legend-water{color:#2563eb}.legend-moss{color:#16a34a}.chart-container{position:relative;height:230px}.chart{width:100%;height:230px;display:block}.chart-point{opacity:0;transition:opacity .12s}.chart-point:hover{opacity:1}#temperature-chart-status:empty,#humidity-chart-status:empty{display:none}.chart text{fill:var(--muted);font:12px "Inter",system-ui,sans-serif}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:20px}.toolbar .debug-switch{margin:0}.debug-switch{display:flex;align-items:center;gap:10px;margin:0 0 20px;font-weight:600}.debug-switch input{width:18px;height:18px;accent-color:var(--accent)}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:left}th,td{padding:12px}th{font-size:.8rem;color:var(--muted)} @media(max-width:700px){.topbar{gap:12px}.topbar .toolbar{gap:12px;justify-content:space-between;width:100%}.card{padding:18px}.grid{grid-template-columns:1fr}.overview-row{grid-template-columns:1fr}.actuator-panel{grid-template-columns:1fr}.water-metrics{gap:12px}.water-metric-label{font-size:.75rem;align-items:start}.mode{min-height:220px}}
    .thermal-bar{position:relative;height:10px;background:linear-gradient(to right,#dbeafe,#bbf7d0 40%,#fde68a 70%,#fecaca);border-radius:8px;margin:18px 0 8px}.thermal-marker{position:absolute;top:-4px;height:18px;width:3px;background:#000}.thermal-target{position:absolute;top:-3px;height:16px;border-left:2px dashed #000}.water-pump{max-width:360px;margin:0 0 24px}.water-pump strong{margin-left:16px;font-size:1.5rem}.water-pump[hidden],#auto-pump-panel[hidden],#manual-pump-panel[hidden]{display:none}</style></head><body><main><header class="topbar"><div class="mode-block"><label class="mode-switch"><input type="checkbox" id="mode-toggle" aria-label="Auto-Modus" disabled><span class="mode-slider"></span></label><div><h1 id="mode">Verbinde …</h1><p class="status" id="mode-status"></p></div></div><div class="toolbar"><label class="debug-switch"><input type="checkbox" id="debug-toggle"> Debug-Modus</label><label><select id="global-period" aria-label="Zeitraum"><option value="10m">10 Minuten</option><option value="1h" selected>1 Stunde</option><option value="24h">24 Stunden</option><option value="7d">7 Tage</option><option value="30d">30 Tage</option></select></label></div></header><div class="grid"><section class="card" id="debug-panel" hidden><p class="label">Sensoren · Rohwerte</p><div class="table-wrap"><table><thead><tr><th>Messwert</th><th>Sensor</th><th>Links</th><th>Rechts</th></tr></thead><tbody><tr><td>Temperatur (°C)</td><td>SHT45</td><td id="left-sht45-temperature_c">–</td><td id="right-sht45-temperature_c">–</td></tr><tr><td>Temperatur (°C)</td><td>SCD40</td><td id="left-scd40-temperature_c">–</td><td id="right-scd40-temperature_c">–</td></tr><tr><td>Luftfeuchtigkeit (%)</td><td>SHT45</td><td id="left-sht45-humidity_pct">–</td><td id="right-sht45-humidity_pct">–</td></tr><tr><td>Luftfeuchtigkeit (%)</td><td>SCD40</td><td id="left-scd40-humidity_pct">–</td><td id="right-scd40-humidity_pct">–</td></tr><tr><td>CO₂ (ppm)</td><td>SCD40</td><td id="left-scd40-co2_ppm">–</td><td id="right-scd40-co2_ppm">–</td></tr><tr><td>Licht (lx)</td><td>BH1750</td><td id="left-bh1750-illuminance_lux">–</td><td id="right-bh1750-illuminance_lux">–</td></tr><tr><td>Wasser</td><td>Ultraschall</td><td><small>Wassersensor (cm)</small><br><span id="tank-ultrasonic-distance_cm">–</span></td><td><small>Wasserstand (max(0; __WATER_OFFSET__ − Rohabstand), cm)</small><br><span id="tank-ultrasonic-water_level_cm">–</span></td></tr><tr><td>Moos 1</td><td>Ultraschall</td><td><small>Abstand (cm)</small><br><span id="moss1-ultrasonic-distance_cm">–</span></td><td><small>__MOSS_FORMULA_1__</small><br><span id="moss1-ultrasonic-height_cm">–</span></td></tr><tr><td>Moos 2</td><td>Ultraschall</td><td><small>Abstand (cm)</small><br><span id="moss2-ultrasonic-distance_cm">–</span></td><td><small>__MOSS_FORMULA_2__</small><br><span id="moss2-ultrasonic-height_cm">–</span></td></tr><tr><td>Moos 3</td><td>Ultraschall</td><td><small>Abstand (cm)</small><br><span id="moss3-ultrasonic-distance_cm">–</span></td><td><small>__MOSS_FORMULA_3__</small><br><span id="moss3-ultrasonic-height_cm">–</span></td></tr><tr><td>Moos 4</td><td>Ultraschall</td><td><small>Abstand (cm)</small><br><span id="moss4-ultrasonic-distance_cm">–</span></td><td><small>__MOSS_FORMULA_4__</small><br><span id="moss4-ultrasonic-height_cm">–</span></td></tr><tr><td>Mooshöhe Ø</td><td>Ultraschall</td><td colspan="2" id="moss-average">–</td></tr></tbody></table></div><p class="status" id="debug-status">Verbinde …</p></section><div class="overview-row"><section class="card camera"><p class="label" id="camera-status" aria-live="polite">Live Feed: Verbinde …</p><img id="camera" alt="Kamerafeed"></section><section class="card actuator-panel" id="actuator-panel" hidden><div id="auto-actuators" hidden><div class="auto-values"><div><span>Lüfter</span><strong id="auto-fan">–</strong></div><div><span>Licht</span><strong id="auto-led">–</strong></div></div><div class="auto-timeline"><div class="auto-timeline-head"><span id="light-phase">Lichtplan</span><span id="light-hours"></span></div><div class="auto-timeline-bar" id="light-timeline" role="img" aria-label="Lichtplan"></div><div class="auto-ticks"><span>00:00</span><span>12:00</span><span>24:00</span></div></div><div class="auto-timeline"><div class="auto-timeline-head"><span id="thermal-status">Temperaturregelung</span><strong id="thermal-value">–</strong></div><div class="thermal-bar" role="img" aria-label="Temperaturregelung" id="thermal-bar"><span class="thermal-target" style="left:40%"></span><span class="thermal-marker" id="thermal-marker" hidden></span></div><div class="auto-ticks"><span id="thermal-low">20 °C</span><span id="thermal-target">Ziel 22 °C</span><span id="thermal-max">Max. 25 °C</span></div></div></div><div id="manual-actuators" hidden><div class="actuator-control"><label for="fan-control">Lüfter <output id="fan-value">–</output></label><input id="fan-control" type="range" min="0" max="100" step="5" disabled></div><div class="actuator-control"><label for="led-control">Licht <output id="led-value">–</output></label><input id="led-control" type="range" min="0" max="100" step="5" disabled></div></div><p class="status actuator-error" id="actuator-error"></p></section></div><section class="card water-panel"><div class="water-metrics"><div><span class="water-metric-label"><i class="legend-target"></i>Zielwasserstand</span><p class="water-value" id="water-target">–</p></div><div><span class="water-metric-label"><i class="legend-water"></i>Wasserstand</span><p class="water-value" id="water">–</p></div><div><span class="water-metric-label"><i class="legend-moss"></i>Moosspitzenhöhe</span><p class="water-value" id="water-moss">–</p></div></div><div class="water-pump" id="water-pump" hidden><div id="auto-pump-panel" hidden><span>Pumpe</span><strong id="auto-pump">–</strong></div><div id="manual-pump-panel" hidden><div class="actuator-control"><label for="pump-control">Pumpe <output id="pump-value">–</output></label><input id="pump-control" type="range" min="0" max="100" step="5" disabled></div></div></div><p class="status" id="water-source"></p><div class="chart-container"><svg class="chart" id="water-chart" viewBox="0 0 800 230" role="img" aria-label="Verlauf von Wasserstand und Mooshöhe"></svg></div><p class="status chart-status" id="water-chart-status">Lade Verlauf …</p></section><section class="card"><div class="temperature-head"><div><p class="label">Temperatur</p><div class="metric-readout"><p class="temperature-value" id="temperature">–</p><p class="status" id="temperature-source">Lade Messwerte …</p></div></div></div><div class="chart-container"><svg class="chart" id="temperature-chart" viewBox="0 0 800 230" role="img" aria-label="Temperaturverlauf"></svg></div><p class="status chart-status" id="temperature-chart-status">Lade Verlauf …</p></section><section class="card"><div class="humidity-head"><div><p class="label">Luftfeuchtigkeit</p><div class="metric-readout"><p class="humidity-value" id="humidity">–</p><p class="status" id="humidity-source">Lade Messwerte …</p></div></div></div><div class="chart-container"><svg class="chart" id="humidity-chart" viewBox="0 0 800 230" role="img" aria-label="Luftfeuchtigkeitverlauf"></svg></div><p class="status chart-status" id="humidity-chart-status">Lade Verlauf …</p></section><section class="card"><div class="co2-head"><div><p class="label">CO₂</p><div class="metric-readout"><p class="co2-value" id="co2">–</p><p class="status" id="co2-source">Lade Messwerte …</p></div></div></div><div class="chart-container"><svg class="chart" id="co2-chart" viewBox="0 0 800 230" role="img" aria-label="CO₂verlauf"></svg></div><p class="status chart-status" id="co2-chart-status">Lade Verlauf …</p></section><section class="card"><div class="light-head"><div><p class="label">Licht</p><div class="metric-readout"><p class="light-value" id="light">–</p><p class="status" id="light-source">Lade Messwerte …</p></div></div></div><div class="chart-container"><svg class="chart" id="light-chart" viewBox="0 0 800 230" role="img" aria-label="Lichtverlauf"></svg></div><p class="status chart-status" id="light-chart-status">Lade Verlauf …</p></section></div></main><script>
    const topbar=document.querySelector('.topbar');
    new ResizeObserver(()=>document.documentElement.style.setProperty('--topbar-height',topbar.getBoundingClientRect().height+'px')).observe(topbar);
    const modeToggle=document.getElementById('mode-toggle');let modePending=false;
    async function updateMode(){try{const response=await fetch('/api/mode',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();const previous=document.documentElement.dataset.mode;document.documentElement.dataset.mode=['AUTO','MANUAL'].includes(data.mode)?data.mode:'';if(previous!==document.documentElement.dataset.mode)window.dispatchEvent(new Event('modechange'));modeToggle.checked=data.mode==='AUTO';modeToggle.disabled=modePending||!document.documentElement.dataset.mode;document.getElementById('mode').textContent=data.mode||'Nicht verfügbar';document.getElementById('mode-status').textContent=data.mode?'':'Verbindung zum Sensorprozess fehlt';return data.mode}catch(e){document.documentElement.dataset.mode='';window.dispatchEvent(new Event('modechange'));modeToggle.disabled=true;document.getElementById('mode').textContent='Nicht verfügbar';document.getElementById('mode-status').textContent='Verbindung zum Dashboard fehlt';return null}}
    modeToggle.addEventListener('change',async()=>{const target=modeToggle.checked?'AUTO':'MANUAL';modeToggle.checked=document.documentElement.dataset.mode==='AUTO';modePending=true;modeToggle.disabled=true;try{const response=await fetch('/api/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:target})});if(!response.ok)throw Error();let confirmed=false;for(let i=0;i<20;i++){await new Promise(resolve=>setTimeout(resolve,250));if(await updateMode()===target){confirmed=true;break}}if(!confirmed)throw Error()}catch(e){document.getElementById('mode-status').textContent='Moduswechsel nicht möglich'}finally{modePending=false;modeToggle.disabled=!['AUTO','MANUAL'].includes(document.documentElement.dataset.mode)}});updateMode();setInterval(updateMode,1000);
    const actuatorPanel=document.getElementById('actuator-panel'), actuatorError=document.getElementById('actuator-error');
    let actuatorGeneration=0, actuatorBusy=false;
    function actuatorVisible(){return ['AUTO','MANUAL'].includes(document.documentElement.dataset.mode)}
    function actuatorEditable(){return document.documentElement.dataset.mode==='MANUAL'}
    function applyActuators(values){for(const device of ['fan','pump','led']){document.getElementById('auto-'+device).textContent=values[device]+' %';const input=document.getElementById(device+'-control');if(!input.matches(':active')){input.value=values[device];document.getElementById(device+'-value').textContent=values[device]+' %'}input.disabled=!actuatorEditable()}}
    async function updateActuators(){if(!actuatorVisible()||actuatorBusy)return;const generation=actuatorGeneration;try{const response=await fetch('/api/actuators',{cache:'no-store'});if(!response.ok)throw Error();const values=await response.json();if(generation!==actuatorGeneration||!actuatorVisible()||actuatorBusy)return;applyActuators(values);if(actuatorError.textContent==='Steuerung nicht erreichbar')actuatorError.textContent=''}catch(e){if(generation===actuatorGeneration&&actuatorVisible()){for(const device of ['fan','pump','led'])document.getElementById(device+'-control').disabled=true;actuatorError.textContent='Steuerung nicht erreichbar'}}}
    function syncActuatorMode(){actuatorGeneration++;document.getElementById("water-pump").hidden=!actuatorVisible();document.getElementById("auto-pump-panel").hidden=document.documentElement.dataset.mode!=="AUTO";document.getElementById("manual-pump-panel").hidden=!actuatorEditable();actuatorPanel.hidden=!actuatorVisible();document.getElementById('auto-actuators').hidden=document.documentElement.dataset.mode!=='AUTO';document.getElementById('manual-actuators').hidden=!actuatorEditable();for(const device of ['fan','pump','led'])document.getElementById(device+'-control').disabled=true;if(!actuatorPanel.hidden)updateActuators()}
    function renderThermal(state){const marker=document.getElementById('thermal-marker');document.getElementById('thermal-status').textContent=state?'Temperatur · '+state.reason:'Temperaturregelung nicht verfügbar';document.getElementById('thermal-value').textContent=state&&state.temperature!==null?state.temperature.toFixed(1).replace('.',',')+' °C':'–';marker.hidden=!state||state.temperature===null;if(!state)return;const low=state.target-2,span=state.maximum-low;marker.style.left=Math.max(0,Math.min(100,(state.temperature-low)/span*100))+'%';document.querySelector('.thermal-target').style.left=((state.target-low)/span*100)+'%';document.getElementById('thermal-low').textContent=low+' °C';document.getElementById('thermal-target').textContent='Ziel '+state.target+' °C';document.getElementById('thermal-max').textContent='Max. '+state.maximum+' °C';document.getElementById('thermal-bar').setAttribute('aria-label','Wärmere Seite '+(state.temperature??'unbekannt')+' °C, Ziel '+state.target+' °C, Maximum '+state.maximum+' °C')}
    async function updateLightSchedule(){if(document.documentElement.dataset.mode!=='AUTO')return;try{const response=await fetch('/api/automatic/light',{cache:'no-store'});if(!response.ok)throw Error();const plan=await response.json();if(document.documentElement.dataset.mode!=='AUTO')return;renderThermal(plan.thermal);const fmt=m=>String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0'), end=(plan.start+plan.duration)%1440;document.getElementById('light-phase').textContent=plan.active?'Zeitplan · Lichtphase':'Zeitplan · Dunkelphase';document.getElementById('light-hours').textContent=fmt(plan.start)+'–'+fmt(end);const bar=document.getElementById('light-timeline');bar.replaceChildren();for(const [start,finish] of (plan.start+plan.duration<=1440?[[plan.start,plan.start+plan.duration]]:[[plan.start,1440],[0,end]])){const segment=document.createElement('span');segment.className='auto-light-segment';segment.style.left=(start/1440*100)+'%';segment.style.width=((finish-start)/1440*100)+'%';bar.appendChild(segment)}const marker=document.createElement('span');marker.className='auto-now';marker.style.left=(plan.current/1440*100)+'%';bar.appendChild(marker);bar.setAttribute('aria-label','Lichtphase '+fmt(plan.start)+' bis '+fmt(end)+', aktuell '+fmt(plan.current))}catch(e){renderThermal(null);document.getElementById('light-phase').textContent='Lichtplan nicht verfügbar';document.getElementById('light-hours').textContent='';document.getElementById('light-timeline').replaceChildren()}}
    window.addEventListener('modechange',()=>{syncActuatorMode();updateLightSchedule()});setInterval(()=>{syncActuatorVisibility();updateActuators();updateLightSchedule()},1000);
    function syncActuatorVisibility(){if(actuatorPanel.hidden===actuatorVisible())syncActuatorMode()}
    for(const device of ['fan','pump','led']){const input=document.getElementById(device+'-control');input.addEventListener('input',()=>document.getElementById(device+'-value').textContent=input.value+' %');input.addEventListener('change',async()=>{actuatorBusy=true;try{const response=await fetch('/api/actuators/'+device,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:Number(input.value)})});if(!response.ok)throw Error(await response.text());if(actuatorVisible())applyActuators(await response.json());actuatorError.textContent=''}catch(e){actuatorError.textContent=e.message||'Steuerung nicht erreichbar'}finally{actuatorBusy=false;updateActuators()}})}
    const chartColors={temperature:'#d97706',humidity:'#0891b2',co2:'#7c3aed',light:'#ca8a04',water:'#2563eb',moss:'#16a34a'};
    function initMetric(metric, unit){
    const periodSelect=document.getElementById('global-period'), chart=document.getElementById(metric+'-chart');
    let temperatureRequest=0;
    function drawTemperature(data){
      chart.replaceChildren();const waterPoints=data.points.filter(p=>p.value!==null&&Number.isFinite(p.value));const mossPoints=data.moss_points||[],targetPoints=data.target_points||[];const points=[...waterPoints,...mossPoints,...targetPoints];
      const status=document.getElementById(metric+'-chart-status');if(!points.length){status.textContent='Keine Messwerte im gewählten Zeitraum';return;}
      status.textContent='';
      const ns='http://www.w3.org/2000/svg', width=800, height=230, left=55, right=20, top=15, bottom=35;
      const span={'10m':600,'1h':3600,'24h':86400,'7d':604800,'30d':2592000}[periodSelect.value], end=Date.now()/1000, start=end-span;
      let low=Math.min(...points.map(p=>p.value)), high=Math.max(...points.map(p=>p.value));const pad=Math.max((high-low)*.1,.5);low-=pad;high+=pad;
      function element(name,attributes){const el=document.createElementNS(ns,name);for(const [key,value] of Object.entries(attributes))el.setAttribute(key,value);chart.appendChild(el);return el}
      const x=t=>left+(t-start)/span*(width-left-right), y=v=>top+(high-v)/(high-low)*(height-top-bottom);
      for(let i=0;i<3;i++){const v=low+(high-low)*i/2, yy=y(v);element('line',{x1:left,x2:width-right,y1:yy,y2:yy,stroke:'var(--grid)'});const label=element('text',{x:0,y:yy+4});label.textContent=v.toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})+' '+unit}
      for(const [seriesIndex,series] of [waterPoints,mossPoints,targetPoints].entries()){let path='',previous=null;for(const point of series){const px=x(point.time),py=y(point.value);if(px<left||px>width-right)continue;path+=(previous===null||(seriesIndex!==2&&point.time-previous>(seriesIndex?data.moss_window_seconds:data.window_seconds)*1.5)?'M':'L')+px+' '+py+' ';previous=point.time}
      if(seriesIndex===2&&series.length)path='M'+left+' '+y(series[0].value)+' L'+(width-right)+' '+y(series[0].value);
      element('path',{d:path,fill:'none',stroke:[chartColors[metric],'#16a34a','#2563eb'][seriesIndex],'stroke-width':'2','stroke-linejoin':'round','stroke-linecap':'round','vector-effect':'non-scaling-stroke',...(seriesIndex===2?{'stroke-dasharray':'6 4'}:{})});}
      for(const point of waterPoints){const px=x(point.time);if(px<left||px>width-right)continue;const circle=element('circle',{cx:px,cy:y(point.value),r:4,fill:chartColors[metric],class:'chart-point'}),title=document.createElementNS(ns,'title');title.textContent=new Date(point.time*1000).toLocaleString('de-DE')+' · '+point.value.toFixed(1)+' '+unit+' · '+point.source;circle.appendChild(title)}
      const tickStep={'10m':120,'1h':600,'24h':14400,'7d':86400,'30d':432000}[periodSelect.value];
      element('line',{x1:left,x2:width-right,y1:height-bottom,y2:height-bottom,stroke:'var(--border)'});
      for(let time=Math.ceil(start/tickStep)*tickStep;time<=end;time+=tickStep){
        const xx=x(time);element('line',{x1:xx,x2:xx,y1:top,y2:height-bottom+5,stroke:'var(--grid)'});
        const label=element('text',{x:xx,y:height-12,'text-anchor':'middle'});
        const options=['10m','1h'].includes(periodSelect.value)?{hour:'2-digit',minute:'2-digit'}:periodSelect.value==='24h'?{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}:{day:'2-digit',month:'2-digit'};
        label.textContent=new Date(time*1000).toLocaleString('de-DE',options);
      }
    }
    async function updateTemperature(){const request=++temperatureRequest;try{const response=await fetch('/api/'+metric+'?period='+periodSelect.value,{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(metric==='water'){try{const mossResponse=await fetch('/api/moss?period='+periodSelect.value,{cache:'no-store'});if(!mossResponse.ok)throw Error();const moss=await mossResponse.json(),windows=new Map();for(const series of Object.values(moss.series))for(const point of series){if(Number.isFinite(point.value)){const values=windows.get(point.time)||[];values.push(point.value);windows.set(point.time,values)}}data.moss_points=[...windows].sort((a,b)=>a[0]-b[0]).map(([time,values])=>({time,value:values.reduce((a,b)=>a+b,0)/values.length}));data.moss_window_seconds=moss.window_seconds;const targetResponse=await fetch('/api/automatic/water',{cache:'no-store'});if(!targetResponse.ok)throw Error();const target=await targetResponse.json();const end=Date.now()/1000,span={'10m':600,'1h':3600,'24h':86400,'7d':604800,'30d':2592000}[periodSelect.value];data.target_points=target.target_cm===null?[]:[{time:end-span,value:target.target_cm},{time:end,value:target.target_cm}]}catch(e){data.moss_points=data.moss_points||[];data.target_points=[]}}if(request!==temperatureRequest)return;drawTemperature(data)}catch(e){if(request!==temperatureRequest)return;chart.replaceChildren();document.getElementById(metric+'-chart-status').textContent='Verlauf nicht erreichbar'}}
    async function updateCurrentTemperature(){if(metric==='water'){try{const response=await fetch('/api/automatic/water',{cache:'no-store'});if(!response.ok)throw Error();const state=await response.json(),fmt=value=>value===null?'–':value.toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})+' cm';document.getElementById('water').textContent=fmt(state.water_level_cm);document.getElementById('water-target').textContent=fmt(state.target_cm);document.getElementById('water-moss').textContent=fmt(state.moss_height_cm);document.getElementById('water-source').textContent=state.reason&&(!state.water_ready||!state.pump_allowed)?state.reason:''}catch(e){for(const id of ['water','water-target','water-moss'])document.getElementById(id).textContent='–';document.getElementById('water-source').textContent='Daten nicht erreichbar'}return}try{const response=await fetch('/api/'+metric+'?current_only=true',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(metric==='moss'){const fmt=v=>v==null?'–':Number(v).toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})+' cm';document.getElementById(metric).textContent='1: '+fmt(data.current.moss1);document.getElementById(metric+'-source').textContent=['2: '+fmt(data.current.moss2)+' ╌','3: '+fmt(data.current.moss3)+' ⋯','4: '+fmt(data.current.moss4)+' – ·'].join('\\n');return}document.getElementById(metric+'').textContent=data.current.value===null?'–':data.current.value.toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})+' '+unit;document.getElementById(metric+'-source').textContent=data.current.source}catch(e){document.getElementById(metric+'').textContent='–';document.getElementById(metric+'-source').textContent='Daten nicht erreichbar'}}
    periodSelect.addEventListener('change',updateTemperature);window.addEventListener('modechange',updateTemperature);updateTemperature();updateCurrentTemperature();setInterval(updateTemperature,30000);setInterval(updateCurrentTemperature,2000);
    }
    initMetric("temperature", "°C");initMetric("humidity", "%");initMetric("co2", "ppm");initMetric("light", "lx");initMetric("water", "cm");
    const debugToggle=document.getElementById('debug-toggle'), debugPanel=document.getElementById('debug-panel'), debugStatus=document.getElementById('debug-status');
    async function updateDebug(){if(!debugToggle.checked)return;try{const response=await fetch('/api/debug/sensors',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(!debugToggle.checked)return;debugPanel.querySelectorAll('tbody [id]').forEach(cell=>cell.textContent='–');for(const reading of data.readings){const cell=document.getElementById(`${reading.side}-${reading.sensor}-${reading.field}`);if(cell)cell.textContent=String(reading.value)}const heights=data.readings.filter(r=>/^moss[1-4]$/.test(r.side)&&r.sensor==='ultrasonic'&&r.field==='height_cm'&&Number.isFinite(r.value)).map(r=>r.value);document.getElementById('moss-average').textContent=heights.length?(heights.reduce((a,b)=>a+b,0)/heights.length).toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})+' cm ('+heights.length+'/4)':'–';debugStatus.textContent=data.readings.length?'':'Keine aktuellen Messwerte';}catch(e){if(debugToggle.checked){debugPanel.querySelectorAll('tbody [id]').forEach(cell=>cell.textContent='–');debugStatus.textContent='Sensordaten nicht erreichbar'}}}
    debugToggle.addEventListener('change',()=>{debugPanel.hidden=!debugToggle.checked;if(debugToggle.checked)updateDebug()});setInterval(updateDebug,1000);
    const camera=document.getElementById('camera');function connectCamera(){camera.src='/camera/stream.mjpg?'+Date.now()}camera.onload=()=>document.getElementById('camera-status').textContent='Live Feed';camera.onerror=()=>{document.getElementById('camera-status').textContent='Live Feed: Nicht erreichbar';setTimeout(connectCamera,3000)};connectCamera();
    </script></body></html>'''.replace('__WATER_OFFSET__', html.escape(setting('WATER_FLOOR_DISTANCE_CM', '8.62').replace('.', ',')))
    for index in range(1, 5):
        reference = setting(f'MOSS_{index}_EMPTY_DISTANCE_CM', '')
        label = (f'Moosspitze (max(0; 6 + {reference.replace(".", ",")} − Rohabstand), cm)'
                 if reference else 'Moosspitze (nicht kalibriert, cm)')
        page = page.replace(f'__MOSS_FORMULA_{index}__', html.escape(label))
    return HTMLResponse(headers={'Cache-Control': 'no-store'}, content=page)


@app.get('/camera/stream.mjpg')
async def camera_stream():
    port = int('8000')
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
