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

from temperature import PERIODS, combine

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
        '((r.sensor == "sht45" or r.sensor == "scd40" or r.sensor == "bh1750") and '
        '(r._field == "temperature_c" or r._field == "humidity_pct" or r._field == "co2_ppm" or r._field == "illuminance_lux") and '
        '(r.side == "left" or r.side == "right") or '
        '(r.side == "tank" and r.sensor == "ultrasonic" and r._field == "water_level_cm")))\n'
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


def metric_data(field, unit, period, current_only):
    if period not in PERIODS:
        return Response('Ungültiger Zeitraum', status_code=400)
    duration, window, function = PERIODS[period]
    if field == "co2_ppm" and period == "10m":
        window = "10s"
    bucket = os.getenv('INFLUXDB_BUCKET', 'moos_sensors')
    org = os.getenv('INFLUXDB_ORG', 'moos')
    sensor_filter = 'r.sensor == "bh1750"' if field == 'illuminance_lux' else 'r.sensor == "sht45" or r.sensor == "scd40"'
    base = (f'from(bucket: {json.dumps(bucket)})\n'
            '  |> range(start: -DURATION)\n'
            '  |> filter(fn: (r) => r._measurement == "moos_sensor" and '
            f'r._field == {json.dumps(field)} and ({sensor_filter}) '
            'and (r.side == "left" or r.side == "right"))\n')
    current_query = base.replace('DURATION', '12s') + '  |> last()'
    history_query = (base.replace('DURATION', duration) +
                     f'  |> aggregateWindow(every: {window}, fn: {function}, createEmpty: false, timeSrc: "_start")')
    try:
        with InfluxDBClient(url=os.getenv('INFLUXDB_URL', 'http://influxdb:8086'),
                            token=os.getenv('INFLUXDB_TOKEN', ''), org=org, timeout=5000) as client:
            api = client.query_api()
            current = {}
            for table in api.query(current_query, org=org):
                for record in table.records:
                    current[(record.values.get('side'), record.values.get('sensor'))] = record.get_value()
            if current_only:
                return {'current': combine(current, unit)}
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
    *{box-sizing:border-box}body{margin:0;background:#eff3ec;color:#213a2c;font:16px system-ui,sans-serif}main{width:100%;padding:clamp(16px,2vw,32px);padding-top:calc(var(--topbar-height,100px) + 24px)}header{margin-bottom:24px}.topbar{position:fixed;top:0;left:0;right:0;z-index:10;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:16px clamp(16px,2vw,32px);background:#eff3ecf5;backdrop-filter:blur(12px);border-bottom:1px solid #dce6d9}.topbar h1{font-size:clamp(1.5rem,3vw,2.4rem);margin:0;line-height:1.2}.topbar .toolbar{margin:0;justify-content:flex-end}.metric-readout{display:flex;align-items:center;gap:clamp(16px,3vw,40px);margin:8px 0 20px}.metric-readout .status{margin:0;line-height:1.4}.metric-readout p{font-variant-numeric:tabular-nums}header p,.label{color:#61796a;font-size:.8rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase}h1{font-size:clamp(2rem,5vw,3.5rem);margin:.25em 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.card{background:#ffffffb8;border:1px solid #e3e9e0;border-radius:12px;padding:24px;min-width:0}.mode{display:flex;flex-direction:column;justify-content:space-between;min-height:310px}.mode strong{font-size:clamp(2rem,4vw,3.5rem);overflow-wrap:anywhere}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#76a77a;margin-right:8px}.camera,#debug-panel{grid-column:1/-1}.camera img{display:block;width:100%;aspect-ratio:16/9;object-fit:contain;background:#1c3024;border-radius:12px}.status:empty{display:none}.status{color:#61796a;font-size:.9rem}#temperature-source,#humidity-source,#co2-source,#light-source{white-space:pre-line}.temperature-head,.humidity-head,.co2-head,.light-head{display:flex;justify-content:space-between;align-items:start;gap:16px;flex-wrap:wrap}.temperature-value,.humidity-value,.co2-value,.light-value{font-size:clamp(2rem,3.5vw,2.8rem);font-weight:700;margin:0}select{appearance:none;-webkit-appearance:none;border:1px solid #cad8c8;border-radius:8px;background-color:white;background-image:url("data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2212%22%20height%3D%228%22%20viewBox%3D%220%200%2012%208%22%3E%3Cpath%20d%3D%22m1%201%205%205%205-5%22%20fill%3D%22none%22%20stroke%3D%22%23213a2c%22%20stroke-width%3D%221.5%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%2F%3E%3C%2Fsvg%3E");background-repeat:no-repeat;background-position:right 14px center;background-size:12px 8px;padding:10px 40px 10px 14px;color:#213a2c;font:inherit;line-height:1.3;cursor:pointer}.chart{width:100%;height:230px;display:block}.chart-point{opacity:0;transition:opacity .12s}.chart-point:hover{opacity:1}#temperature-chart-status:empty,#humidity-chart-status:empty{display:none}.chart text{fill:#61796a;font:12px system-ui}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:20px}.toolbar .debug-switch{margin:0}.debug-switch{display:flex;align-items:center;gap:10px;margin:0 0 20px;font-weight:600}.debug-switch input{width:18px;height:18px;accent-color:#426b4b}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:left}th,td{padding:12px;border-bottom:1px solid #e4ebe2}th{font-size:.8rem;color:#61796a} @media(max-width:700px){.topbar{gap:12px}.topbar .toolbar{gap:12px;justify-content:space-between;width:100%}.card{padding:18px}.grid{grid-template-columns:1fr}.mode{min-height:220px}}
    </style></head><body><main><header class="topbar"><div class="mode-block"><h1 id="mode">Verbinde …</h1><p class="status" id="mode-status"></p></div><div class="toolbar"><label class="debug-switch"><input type="checkbox" id="debug-toggle"> Debug-Modus</label><label>Zeitraum <select id="global-period"><option value="10m">10 Minuten</option><option value="1h" selected>1 Stunde</option><option value="24h">24 Stunden</option><option value="7d">7 Tage</option><option value="30d">30 Tage</option></select></label></div></header><div class="grid"><section class="card" id="debug-panel" hidden><p class="label">Sensoren · Rohwerte</p><div class="table-wrap"><table><thead><tr><th>Messwert</th><th>Sensor</th><th>Links</th><th>Rechts</th></tr></thead><tbody><tr><td>Temperatur (°C)</td><td>SHT45</td><td id="left-sht45-temperature_c">–</td><td id="right-sht45-temperature_c">–</td></tr><tr><td>Temperatur (°C)</td><td>SCD40</td><td id="left-scd40-temperature_c">–</td><td id="right-scd40-temperature_c">–</td></tr><tr><td>Luftfeuchtigkeit (%)</td><td>SHT45</td><td id="left-sht45-humidity_pct">–</td><td id="right-sht45-humidity_pct">–</td></tr><tr><td>Luftfeuchtigkeit (%)</td><td>SCD40</td><td id="left-scd40-humidity_pct">–</td><td id="right-scd40-humidity_pct">–</td></tr><tr><td>CO₂ (ppm)</td><td>SCD40</td><td id="left-scd40-co2_ppm">–</td><td id="right-scd40-co2_ppm">–</td></tr><tr><td>Licht (lx)</td><td>BH1750</td><td id="left-bh1750-illuminance_lux">–</td><td id="right-bh1750-illuminance_lux">–</td></tr><tr><td>Wasserstand (cm)</td><td>Ultraschall</td><td id="tank-ultrasonic-water_level_cm" colspan="2">–</td></tr></tbody></table></div><p class="status" id="debug-status">Verbinde …</p></section><section class="card"><div class="temperature-head"><div><p class="label">Temperatur</p><div class="metric-readout"><p class="temperature-value" id="temperature">–</p><p class="status" id="temperature-source">Lade Messwerte …</p></div></div></div><svg class="chart" id="temperature-chart" viewBox="0 0 800 230" role="img" aria-label="Temperaturverlauf"></svg><p class="status" id="temperature-chart-status">Lade Verlauf …</p></section><section class="card"><div class="humidity-head"><div><p class="label">Luftfeuchtigkeit</p><div class="metric-readout"><p class="humidity-value" id="humidity">–</p><p class="status" id="humidity-source">Lade Messwerte …</p></div></div></div><svg class="chart" id="humidity-chart" viewBox="0 0 800 230" role="img" aria-label="Luftfeuchtigkeitverlauf"></svg><p class="status" id="humidity-chart-status">Lade Verlauf …</p></section><section class="card"><div class="co2-head"><div><p class="label">CO₂</p><div class="metric-readout"><p class="co2-value" id="co2">–</p><p class="status" id="co2-source">Lade Messwerte …</p></div></div></div><svg class="chart" id="co2-chart" viewBox="0 0 800 230" role="img" aria-label="CO₂verlauf"></svg><p class="status" id="co2-chart-status">Lade Verlauf …</p></section><section class="card"><div class="light-head"><div><p class="label">Licht</p><div class="metric-readout"><p class="light-value" id="light">–</p><p class="status" id="light-source">Lade Messwerte …</p></div></div></div><svg class="chart" id="light-chart" viewBox="0 0 800 230" role="img" aria-label="Lichtverlauf"></svg><p class="status" id="light-chart-status">Lade Verlauf …</p></section><section class="card camera"><p class="label" id="camera-status" aria-live="polite">Kamera: Verbinde …</p><img id="camera" alt="Kamerafeed"></section></div></main><script>
    const topbar=document.querySelector('.topbar');
    new ResizeObserver(()=>document.documentElement.style.setProperty('--topbar-height',topbar.getBoundingClientRect().height+'px')).observe(topbar);
    async function updateMode(){try{const response=await fetch('/api/mode',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();document.getElementById('mode').textContent=data.mode||'Nicht verfügbar';document.getElementById('mode-status').textContent=data.mode?'':'Verbindung zum Sensorprozess fehlt';}catch(e){document.getElementById('mode').textContent='Nicht verfügbar';document.getElementById('mode-status').textContent='Verbindung zum Dashboard fehlt';}}updateMode();setInterval(updateMode,1000);
    function initMetric(metric, unit){
    const periodSelect=document.getElementById('global-period'), chart=document.getElementById(metric+'-chart');
    let temperatureRequest=0;
    function drawTemperature(data){
      chart.replaceChildren();const points=data.points.filter(p=>p.value!==null&&Number.isFinite(p.value));
      const status=document.getElementById(metric+'-chart-status');if(!points.length){status.textContent='Keine Messwerte im gewählten Zeitraum';return;}
      status.textContent='';
      const ns='http://www.w3.org/2000/svg', width=800, height=230, left=55, right=20, top=15, bottom=35;
      const span={'10m':600,'1h':3600,'24h':86400,'7d':604800,'30d':2592000}[periodSelect.value], end=Date.now()/1000, start=end-span;
      let low=Math.min(...points.map(p=>p.value)), high=Math.max(...points.map(p=>p.value));const pad=Math.max((high-low)*.1,.5);low-=pad;high+=pad;
      function element(name,attributes){const el=document.createElementNS(ns,name);for(const [key,value] of Object.entries(attributes))el.setAttribute(key,value);chart.appendChild(el);return el}
      const x=t=>left+(t-start)/span*(width-left-right), y=v=>top+(high-v)/(high-low)*(height-top-bottom);
      for(let i=0;i<3;i++){const v=low+(high-low)*i/2, yy=y(v);element('line',{x1:left,x2:width-right,y1:yy,y2:yy,stroke:'#e2ebe0'});const label=element('text',{x:0,y:yy+4});label.textContent=v.toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})+' '+unit}
      let path='',previous=null;for(const point of points){const px=x(point.time),py=y(point.value);if(px<left||px>width-right)continue;path+=(previous===null||point.time-previous>data.window_seconds*1.5?'M':'L')+px+' '+py+' ';previous=point.time}
      element('path',{d:path,fill:'none',stroke:'#4e865b','stroke-width':'2','stroke-linejoin':'round','stroke-linecap':'round','vector-effect':'non-scaling-stroke'});
      for(const point of points){const px=x(point.time);if(px<left||px>width-right)continue;const circle=element('circle',{cx:px,cy:y(point.value),r:4,fill:'#4e865b',class:'chart-point'}),title=document.createElementNS(ns,'title');title.textContent=new Date(point.time*1000).toLocaleString('de-DE')+' · '+point.value.toFixed(1)+' '+unit+' · '+point.source;circle.appendChild(title)}
      const tickStep={'10m':120,'1h':600,'24h':14400,'7d':86400,'30d':432000}[periodSelect.value];
      element('line',{x1:left,x2:width-right,y1:height-bottom,y2:height-bottom,stroke:'#c6d5c4'});
      for(let time=Math.ceil(start/tickStep)*tickStep;time<=end;time+=tickStep){
        const xx=x(time);element('line',{x1:xx,x2:xx,y1:top,y2:height-bottom+5,stroke:'#e2ebe0'});
        const label=element('text',{x:xx,y:height-12,'text-anchor':'middle'});
        const options=['10m','1h'].includes(periodSelect.value)?{hour:'2-digit',minute:'2-digit'}:periodSelect.value==='24h'?{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}:{day:'2-digit',month:'2-digit'};
        label.textContent=new Date(time*1000).toLocaleString('de-DE',options);
      }
    }
    async function updateTemperature(){const request=++temperatureRequest;try{const response=await fetch('/api/'+metric+'?period='+periodSelect.value,{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(request!==temperatureRequest)return;drawTemperature(data)}catch(e){if(request!==temperatureRequest)return;chart.replaceChildren();document.getElementById(metric+'-chart-status').textContent='Verlauf nicht erreichbar'}}
    async function updateCurrentTemperature(){try{const response=await fetch('/api/'+metric+'?current_only=true',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();document.getElementById(metric+'').textContent=data.current.value===null?'–':data.current.value.toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})+' '+unit;document.getElementById(metric+'-source').textContent=data.current.source}catch(e){document.getElementById(metric+'').textContent='–';document.getElementById(metric+'-source').textContent='Daten nicht erreichbar'}}
    periodSelect.addEventListener('change',updateTemperature);updateTemperature();updateCurrentTemperature();setInterval(updateTemperature,30000);setInterval(updateCurrentTemperature,2000);
    }
    initMetric("temperature", "°C");initMetric("humidity", "%");initMetric("co2", "ppm");initMetric("light", "lx");
    const debugToggle=document.getElementById('debug-toggle'), debugPanel=document.getElementById('debug-panel'), debugStatus=document.getElementById('debug-status');
    async function updateDebug(){if(!debugToggle.checked)return;try{const response=await fetch('/api/debug/sensors',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(!debugToggle.checked)return;debugPanel.querySelectorAll('tbody td[id]').forEach(cell=>cell.textContent='–');for(const reading of data.readings){const cell=document.getElementById(`${reading.side}-${reading.sensor}-${reading.field}`);if(cell)cell.textContent=String(reading.value)}debugStatus.textContent=data.readings.length?'Aktuelle Messwerte':'Keine aktuellen Messwerte';}catch(e){if(debugToggle.checked){debugPanel.querySelectorAll('tbody td[id]').forEach(cell=>cell.textContent='–');debugStatus.textContent='Sensordaten nicht erreichbar'}}}
    debugToggle.addEventListener('change',()=>{debugPanel.hidden=!debugToggle.checked;if(debugToggle.checked)updateDebug()});setInterval(updateDebug,1000);
    const camera=document.getElementById('camera');function connectCamera(){camera.src='/camera/stream.mjpg?'+Date.now()}camera.onload=()=>document.getElementById('camera-status').textContent='Kamera: Live';camera.onerror=()=>{document.getElementById('camera-status').textContent='Kamera: Nicht erreichbar';setTimeout(connectCamera,3000)};connectCamera();
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
