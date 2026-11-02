"""Dashboard for the current operating mode and camera."""
import json
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from influxdb_client import InfluxDBClient

app = FastAPI(title="Moosbox")
MODE_FILE = Path('/run/moos/mode.json')
LOG = logging.getLogger('moos.dashboard')


@app.get('/api/debug/sensors')
def debug_sensors():
    """Return the latest stored sensor readings without aggregation."""
    bucket = os.getenv('INFLUXDB_BUCKET', 'moos_sensors')
    org = os.getenv('INFLUXDB_ORG', 'moos')
    query = (
        f'from(bucket: {json.dumps(bucket)})\n'
        '  |> range(start: -12s)\n'
        '  |> filter(fn: (r) => r._measurement == "moos_sensor" and '
        '(r.sensor == "sht45" or r.sensor == "scd40") and '
        '(r._field == "temperature_c" or r._field == "humidity_pct") and '
        '(r.side == "left" or r.side == "right"))\n'
        '  |> last()'
    )
    try:
        with InfluxDBClient(url=os.getenv('INFLUXDB_URL', 'http://influxdb:8086'),
                            token=os.getenv('INFLUXDB_TOKEN', ''), org=org, timeout=5000) as client:
            readings = [
                {'side': record.values.get('side'), 'sensor': record.values.get('sensor'),
                 'field': record.get_field(), 'value': record.get_value()}
                for table in client.query_api().query(query, org=org)
                for record in table.records
            ]
        return {'readings': readings}
    except Exception:
        LOG.exception('Could not read debug sensor values')
        return Response('Sensordaten nicht erreichbar', status_code=503)


@app.get('/api/mode')
def mode():
    try:
        data = json.loads(MODE_FILE.read_text())
        if data['mode'] in ('AUTO', 'MAINTENANCE', 'MEASURING') and 0 <= time.time() - data['updated'] < 5:
            return {'mode': data['mode']}
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return {'mode': None}


@app.get('/', response_class=HTMLResponse)
def index():
    return HTMLResponse('''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Moosbox</title><style>
    *{box-sizing:border-box}body{margin:0;background:#eff3ec;color:#213a2c;font:16px system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:clamp(24px,5vw,64px)}header{margin-bottom:36px}header p,.label{color:#61796a;font-size:.8rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase}h1{font-size:clamp(2rem,5vw,3.5rem);margin:.25em 0}.grid{display:grid;grid-template-columns:minmax(0, 1fr);gap:20px}.card{background:white;border:1px solid #dce6d9;border-radius:20px;padding:28px;box-shadow:0 8px 28px #233b2910}.mode{display:flex;flex-direction:column;justify-content:space-between;min-height:310px}.mode strong{font-size:clamp(2rem,4vw,3.5rem);overflow-wrap:anywhere}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#76a77a;margin-right:8px}.camera img{display:block;width:100%;aspect-ratio:16/9;object-fit:contain;background:#1c3024;border-radius:12px}.status{color:#61796a;font-size:.9rem}.debug-switch{display:flex;align-items:center;gap:10px;margin:0 0 20px;font-weight:600}.debug-switch input{width:18px;height:18px;accent-color:#426b4b}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:left}th,td{padding:12px;border-bottom:1px solid #e4ebe2}th{font-size:.8rem;color:#61796a} @media(max-width:700px){.grid{grid-template-columns:1fr}.mode{min-height:220px}}
    </style></head><body><main><header><p>Moosbox</p><span class="label">Aktueller Modus</span><h1 id="mode">Verbinde …</h1><p class="status" id="mode-status">Modus wird geladen</p></header><label class="debug-switch"><input type="checkbox" id="debug-toggle"> Debug-Modus</label><div class="grid"><section class="card camera"><p class="label">Kamera</p><img id="camera" alt="Kamerafeed"><p class="status" id="camera-status">Verbinde …</p></section><section class="card" id="debug-panel" hidden><p class="label">Sensoren · Rohwerte</p><div class="table-wrap"><table><thead><tr><th>Messwert</th><th>Sensor</th><th>Links</th><th>Rechts</th></tr></thead><tbody><tr><td>Temperatur (°C)</td><td>SHT45</td><td id="left-sht45-temperature_c">–</td><td id="right-sht45-temperature_c">–</td></tr><tr><td>Temperatur (°C)</td><td>SCD40</td><td id="left-scd40-temperature_c">–</td><td id="right-scd40-temperature_c">–</td></tr><tr><td>Luftfeuchtigkeit (%)</td><td>SHT45</td><td id="left-sht45-humidity_pct">–</td><td id="right-sht45-humidity_pct">–</td></tr><tr><td>Luftfeuchtigkeit (%)</td><td>SCD40</td><td id="left-scd40-humidity_pct">–</td><td id="right-scd40-humidity_pct">–</td></tr></tbody></table></div><p class="status" id="debug-status">Verbinde …</p></section></div></main><script>
    async function updateMode(){try{const response=await fetch('/api/mode',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();document.getElementById('mode').textContent=data.mode||'Nicht verfügbar';document.getElementById('mode-status').textContent=data.mode?'Aktueller Betriebsmodus':'Verbindung zum Sensorprozess fehlt';}catch(e){document.getElementById('mode').textContent='Nicht verfügbar';document.getElementById('mode-status').textContent='Verbindung zum Dashboard fehlt';}}updateMode();setInterval(updateMode,1000);
    const debugToggle=document.getElementById('debug-toggle'), debugPanel=document.getElementById('debug-panel'), debugStatus=document.getElementById('debug-status');
    async function updateDebug(){if(!debugToggle.checked)return;try{const response=await fetch('/api/debug/sensors',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(!debugToggle.checked)return;debugPanel.querySelectorAll('tbody td[id]').forEach(cell=>cell.textContent='–');for(const reading of data.readings){const cell=document.getElementById(`${reading.side}-${reading.sensor}-${reading.field}`);if(cell)cell.textContent=String(reading.value)}debugStatus.textContent=data.readings.length?'Aktuelle Messwerte':'Keine aktuellen Messwerte';}catch(e){if(debugToggle.checked){debugPanel.querySelectorAll('tbody td[id]').forEach(cell=>cell.textContent='–');debugStatus.textContent='Sensordaten nicht erreichbar'}}}
    debugToggle.addEventListener('change',()=>{debugPanel.hidden=!debugToggle.checked;if(debugToggle.checked)updateDebug()});setInterval(updateDebug,1000);
    const camera=document.getElementById('camera');function connectCamera(){camera.src='/camera/stream.mjpg?'+Date.now()}camera.onload=()=>document.getElementById('camera-status').textContent='Live';camera.onerror=()=>{document.getElementById('camera-status').textContent='Kamera nicht erreichbar';setTimeout(connectCamera,3000)};connectCamera();
    </script></body></html>''')


@app.get('/camera/stream.mjpg')
async def camera_stream():
    port = int(os.getenv('CAMERA_PORT', '8000'))
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
