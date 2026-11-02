"""Dashboard for the current operating mode and camera."""
import json
import html
import logging
import time
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from influxdb_client import InfluxDBClient

from configuration import setting

from temperature import PERIODS, combine

app = FastAPI(title="Moosbox")
MODE_FILE = Path('/run/moos/mode.json')
LOG = logging.getLogger('moos.dashboard')


@app.get('/api/debug/sensors')
def debug_sensors():
    """Return the latest stored sensor readings without aggregation."""
    bucket = setting('INFLUXDB_BUCKET', 'moos_sensors')
    org = setting('INFLUXDB_ORG', 'moos')
    query = (
        f'from(bucket: {json.dumps(bucket)})\n'
        '  |> range(start: -12s)\n'
        '  |> filter(fn: (r) => r._measurement == "moos_sensor" and '
        '((r.sensor == "sht45" or r.sensor == "scd40" or r.sensor == "bh1750") and '
        '(r._field == "temperature_c" or r._field == "humidity_pct" or r._field == "co2_ppm" or r._field == "illuminance_lux") and '
        '(r.side == "left" or r.side == "right") or '
        '(r.sensor == "ultrasonic" and ((r.side == "tank" and (r._field == "distance_cm" or r._field == "water_level_cm")) or ((r.side == "moss1" or r.side == "moss2" or r.side == "moss3" or r.side == "moss4") and (r._field == "distance_cm" or r._field == "height_cm"))))))\n'
        '  |> last()'
    )
    try:
        with InfluxDBClient(url=setting('INFLUXDB_URL', 'http://influxdb:8086'),
                            token=setting('INFLUXDB_TOKEN', ''), org=org, timeout=5000) as client:
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
    current_query = base.replace('DURATION', '12s') + '  |> last()'
    history_query = (base.replace('DURATION', duration) +
                     f'  |> aggregateWindow(every: {window}, fn: {function}, createEmpty: false, timeSrc: "_start")')
    try:
        with InfluxDBClient(url=setting('INFLUXDB_URL', 'http://influxdb:8086'),
                            token=setting('INFLUXDB_TOKEN', ''), org=org, timeout=5000) as client:
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
            'and r._field == "height_cm" and (r.side == "moss1" or r.side == "moss2" or r.side == "moss3" or r.side == "moss4"))\n')
    try:
        with InfluxDBClient(url=setting('INFLUXDB_URL', 'http://influxdb:8086'),
                            token=setting('INFLUXDB_TOKEN', ''), org=org, timeout=5000) as client:
            api = client.query_api()
            current = {}
            for table in api.query(base.replace('DURATION', '12s') + '  |> last()', org=org):
                for record in table.records:
                    current[record.values.get('side')] = record.get_value()
            if current_only:
                return {'current': current}
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
    try:
        data = json.loads(MODE_FILE.read_text())
        if data['mode'] in ('AUTO', 'MAINTENANCE', 'MEASURING') and 0 <= time.time() - data['updated'] < 5:
            return {'mode': data['mode']}
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return {'mode': None}


@app.get('/', response_class=HTMLResponse)
def index():
    return HTMLResponse(headers={'Cache-Control': 'no-store'}, content='''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Moosbox</title><link rel="stylesheet" href="https://rsms.me/inter/inter.css"><style>
:root{--page:#fff;--bar:#fff;--text:#000;--muted:#000;--border:#d4d4d4;--grid:#e5e5e5;--accent:#404040;--dark:#171717;--backdrop:#00000066;--mode-color:#15803d}
:root[data-mode="MAINTENANCE"]{--mode-color:#1d4ed8}
:root[data-mode="MEASURING"]{--mode-color:#a16207}

    *{box-sizing:border-box}html{background:#fff;color-scheme:light}body{min-height:100vh;margin:0;background:#fff;color:var(--text);font:16px "Inter",system-ui,sans-serif}main{background:#fff;min-height:100vh;width:100%;padding:clamp(16px,2vw,32px);padding-top:calc(var(--topbar-height,100px) + 24px)}header{margin-bottom:24px}.topbar{position:fixed;top:0;left:0;right:0;z-index:10;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:16px clamp(16px,2vw,32px);background:#fff;backdrop-filter:blur(12px);border-bottom:1px solid var(--border)}.topbar h1{color:#000;font-size:clamp(1.5rem,3vw,2.4rem);margin:0;line-height:1.2}.topbar .toolbar{margin:0;justify-content:flex-end}.metric-readout{display:flex;align-items:center;gap:clamp(16px,3vw,40px);margin:8px 0 20px}.metric-readout .status{margin:0;line-height:1.4}.metric-readout p{font-variant-numeric:tabular-nums}header p,.label{color:var(--muted);font-size:.8rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase}h1{font-size:clamp(2rem,5vw,3.5rem);margin:.25em 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.card{background:transparent;border:0;border-radius:0;padding:24px;min-width:0}.mode{display:flex;flex-direction:column;justify-content:space-between;min-height:310px}.mode strong{font-size:clamp(2rem,4vw,3.5rem);overflow-wrap:anywhere}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--accent);margin-right:8px}#debug-panel{grid-column:1/-1}.camera img{display:block;width:100%;aspect-ratio:16/9;object-fit:contain;background:var(--dark);border-radius:12px}.status:empty{display:none}.status{color:var(--muted);font-size:.9rem}#temperature-source,#humidity-source,#co2-source,#light-source,#water-source,#moss-source{white-space:pre-line}.temperature-head,.humidity-head,.co2-head,.light-head,.water-head,.moss-head{display:flex;justify-content:space-between;align-items:start;gap:16px;flex-wrap:wrap}.temperature-value,.humidity-value,.co2-value,.light-value,.water-value,.moss-value{font-size:clamp(2rem,3.5vw,2.8rem);font-weight:700;margin:0}select{appearance:none;-webkit-appearance:none;border:1px solid var(--border);border-radius:8px;background-color:white;background-image:url("data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2212%22%20height%3D%228%22%20viewBox%3D%220%200%2012%208%22%3E%3Cpath%20d%3D%22m1%201%205%205%205-5%22%20fill%3D%22none%22%20stroke%3D%22%23000000%22%20stroke-width%3D%221.5%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%2F%3E%3C%2Fsvg%3E");background-repeat:no-repeat;background-position:right 14px center;background-size:12px 8px;padding:10px 40px 10px 14px;color:var(--text);font:inherit;line-height:1.3;cursor:pointer}.chart-legend{display:flex;gap:20px;font-size:.8rem}.chart-legend i{display:inline-block;width:20px;border-top:2px solid;vertical-align:middle;margin-right:6px}.legend-water{color:#2563eb}.legend-moss{color:#16a34a;border-top-style:dashed!important}.chart{width:100%;height:230px;display:block}.chart-point{opacity:0;transition:opacity .12s}.chart-point:hover{opacity:1}#temperature-chart-status:empty,#humidity-chart-status:empty{display:none}.chart text{fill:var(--muted);font:12px "Inter",system-ui,sans-serif}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:20px}.toolbar .debug-switch{margin:0}.debug-switch{display:flex;align-items:center;gap:10px;margin:0 0 20px;font-weight:600}.debug-switch input{width:18px;height:18px;accent-color:var(--accent)}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:left}th,td{padding:12px}th{font-size:.8rem;color:var(--muted)} @media(max-width:700px){.topbar{gap:12px}.topbar .toolbar{gap:12px;justify-content:space-between;width:100%}.card{padding:18px}.grid{grid-template-columns:1fr}.mode{min-height:220px}}
    </style></head><body><main><header class="topbar"><div class="mode-block"><h1 id="mode">Verbinde …</h1><p class="status" id="mode-status"></p></div><div class="toolbar"><label class="debug-switch"><input type="checkbox" id="debug-toggle"> Debug-Modus</label><label><select id="global-period" aria-label="Zeitraum"><option value="10m">10 Minuten</option><option value="1h" selected>1 Stunde</option><option value="24h">24 Stunden</option><option value="7d">7 Tage</option><option value="30d">30 Tage</option></select></label></div></header><div class="grid"><section class="card" id="debug-panel" hidden><p class="label">Sensoren · Rohwerte</p><div class="table-wrap"><table><thead><tr><th>Messwert</th><th>Sensor</th><th>Links</th><th>Rechts</th></tr></thead><tbody><tr><td>Temperatur (°C)</td><td>SHT45</td><td id="left-sht45-temperature_c">–</td><td id="right-sht45-temperature_c">–</td></tr><tr><td>Temperatur (°C)</td><td>SCD40</td><td id="left-scd40-temperature_c">–</td><td id="right-scd40-temperature_c">–</td></tr><tr><td>Luftfeuchtigkeit (%)</td><td>SHT45</td><td id="left-sht45-humidity_pct">–</td><td id="right-sht45-humidity_pct">–</td></tr><tr><td>Luftfeuchtigkeit (%)</td><td>SCD40</td><td id="left-scd40-humidity_pct">–</td><td id="right-scd40-humidity_pct">–</td></tr><tr><td>CO₂ (ppm)</td><td>SCD40</td><td id="left-scd40-co2_ppm">–</td><td id="right-scd40-co2_ppm">–</td></tr><tr><td>Licht (lx)</td><td>BH1750</td><td id="left-bh1750-illuminance_lux">–</td><td id="right-bh1750-illuminance_lux">–</td></tr><tr><td>Wasser</td><td>Ultraschall</td><td><small>Wassersensor (cm)</small><br><span id="tank-ultrasonic-distance_cm">–</span></td><td><small>Wasserstand (max(0; __WATER_OFFSET__ − Rohabstand), cm)</small><br><span id="tank-ultrasonic-water_level_cm">–</span></td></tr><tr><td>Moos 1</td><td>Ultraschall</td><td><small>Abstand (cm)</small><br><span id="moss1-ultrasonic-distance_cm">–</span></td><td><small>Mooshöhe (cm)</small><br><span id="moss1-ultrasonic-height_cm">–</span></td></tr><tr><td>Moos 2</td><td>Ultraschall</td><td><small>Abstand (cm)</small><br><span id="moss2-ultrasonic-distance_cm">–</span></td><td><small>Mooshöhe (cm)</small><br><span id="moss2-ultrasonic-height_cm">–</span></td></tr><tr><td>Moos 3</td><td>Ultraschall</td><td><small>Abstand (cm)</small><br><span id="moss3-ultrasonic-distance_cm">–</span></td><td><small>Mooshöhe (cm)</small><br><span id="moss3-ultrasonic-height_cm">–</span></td></tr><tr><td>Moos 4</td><td>Ultraschall</td><td><small>Abstand (cm)</small><br><span id="moss4-ultrasonic-distance_cm">–</span></td><td><small>Mooshöhe (cm)</small><br><span id="moss4-ultrasonic-height_cm">–</span></td></tr><tr><td>Mooshöhe Ø</td><td>Ultraschall</td><td colspan="2" id="moss-average">–</td></tr></tbody></table></div><p class="status" id="debug-status">Verbinde …</p></section><section class="card"><div class="temperature-head"><div><p class="label">Temperatur</p><div class="metric-readout"><p class="temperature-value" id="temperature">–</p><p class="status" id="temperature-source">Lade Messwerte …</p></div></div></div><svg class="chart" id="temperature-chart" viewBox="0 0 800 230" role="img" aria-label="Temperaturverlauf"></svg><p class="status" id="temperature-chart-status">Lade Verlauf …</p></section><section class="card"><div class="humidity-head"><div><p class="label">Luftfeuchtigkeit</p><div class="metric-readout"><p class="humidity-value" id="humidity">–</p><p class="status" id="humidity-source">Lade Messwerte …</p></div></div></div><svg class="chart" id="humidity-chart" viewBox="0 0 800 230" role="img" aria-label="Luftfeuchtigkeitverlauf"></svg><p class="status" id="humidity-chart-status">Lade Verlauf …</p></section><section class="card"><div class="co2-head"><div><p class="label">CO₂</p><div class="metric-readout"><p class="co2-value" id="co2">–</p><p class="status" id="co2-source">Lade Messwerte …</p></div></div></div><svg class="chart" id="co2-chart" viewBox="0 0 800 230" role="img" aria-label="CO₂verlauf"></svg><p class="status" id="co2-chart-status">Lade Verlauf …</p></section><section class="card"><div class="light-head"><div><p class="label">Licht</p><div class="metric-readout"><p class="light-value" id="light">–</p><p class="status" id="light-source">Lade Messwerte …</p></div></div></div><svg class="chart" id="light-chart" viewBox="0 0 800 230" role="img" aria-label="Lichtverlauf"></svg><p class="status" id="light-chart-status">Lade Verlauf …</p></section><section class="card"><div class="water-head"><div><p class="label">Wasserstand</p><div class="metric-readout"><p class="water-value" id="water">–</p><p class="status" id="water-source">Lade Messwerte …</p></div></div></div><div class="chart-legend"><span><i class="legend-water"></i>Wasserstand</span><span><i class="legend-moss"></i>Mooshöhe Ø</span></div><svg class="chart" id="water-chart" viewBox="0 0 800 230" role="img" aria-label="Wasserstandverlauf"></svg><p class="status" id="water-chart-status">Lade Verlauf …</p></section><section class="card camera"><p class="label" id="camera-status" aria-live="polite">Kamera: Verbinde …</p><img id="camera" alt="Kamerafeed"></section></div></main><script>
    const topbar=document.querySelector('.topbar');
    new ResizeObserver(()=>document.documentElement.style.setProperty('--topbar-height',topbar.getBoundingClientRect().height+'px')).observe(topbar);
    async function updateMode(){try{const response=await fetch('/api/mode',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(['AUTO','MAINTENANCE','MEASURING'].includes(data.mode))document.documentElement.dataset.mode=data.mode;document.getElementById('mode').textContent=data.mode||'Nicht verfügbar';document.getElementById('mode-status').textContent=data.mode?'':'Verbindung zum Sensorprozess fehlt';}catch(e){document.getElementById('mode').textContent='Nicht verfügbar';document.getElementById('mode-status').textContent='Verbindung zum Dashboard fehlt';}}updateMode();setInterval(updateMode,1000);
    const chartColors={temperature:'#d97706',humidity:'#0891b2',co2:'#7c3aed',light:'#ca8a04',water:'#2563eb',moss:'#16a34a'};
    function initMetric(metric, unit){
    const periodSelect=document.getElementById('global-period'), chart=document.getElementById(metric+'-chart');
    let temperatureRequest=0;
    function drawTemperature(data){
      chart.replaceChildren();const waterPoints=data.points.filter(p=>p.value!==null&&Number.isFinite(p.value));const mossPoints=data.moss_points||[];const points=[...waterPoints,...mossPoints];
      const status=document.getElementById(metric+'-chart-status');if(!points.length){status.textContent='Keine Messwerte im gewählten Zeitraum';return;}
      status.textContent='';
      const ns='http://www.w3.org/2000/svg', width=800, height=230, left=55, right=20, top=15, bottom=35;
      const span={'10m':600,'1h':3600,'24h':86400,'7d':604800,'30d':2592000}[periodSelect.value], end=Date.now()/1000, start=end-span;
      let low=Math.min(...points.map(p=>p.value)), high=Math.max(...points.map(p=>p.value));const pad=Math.max((high-low)*.1,.5);low-=pad;high+=pad;
      function element(name,attributes){const el=document.createElementNS(ns,name);for(const [key,value] of Object.entries(attributes))el.setAttribute(key,value);chart.appendChild(el);return el}
      const x=t=>left+(t-start)/span*(width-left-right), y=v=>top+(high-v)/(high-low)*(height-top-bottom);
      for(let i=0;i<3;i++){const v=low+(high-low)*i/2, yy=y(v);element('line',{x1:left,x2:width-right,y1:yy,y2:yy,stroke:'var(--grid)'});const label=element('text',{x:0,y:yy+4});label.textContent=v.toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})+' '+unit}
      for(const [seriesIndex,series] of [waterPoints,mossPoints].entries()){let path='',previous=null;for(const point of series){const px=x(point.time),py=y(point.value);if(px<left||px>width-right)continue;path+=(previous===null||point.time-previous>(seriesIndex?data.moss_window_seconds:data.window_seconds)*1.5?'M':'L')+px+' '+py+' ';previous=point.time}
      element('path',{d:path,fill:'none',stroke:seriesIndex?'#16a34a':chartColors[metric],'stroke-width':'2','stroke-linejoin':'round','stroke-linecap':'round','vector-effect':'non-scaling-stroke',...(seriesIndex?{'stroke-dasharray':['','6 4','2 4','8 3 2 3'][seriesIndex]}:{})});}
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
    async function updateTemperature(){const request=++temperatureRequest;try{const response=await fetch('/api/'+metric+'?period='+periodSelect.value,{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(metric==='water'){try{const mossResponse=await fetch('/api/moss?period='+periodSelect.value,{cache:'no-store'});if(!mossResponse.ok)throw Error();const moss=await mossResponse.json(),windows=new Map();for(const series of Object.values(moss.series))for(const point of series){if(Number.isFinite(point.value)){const values=windows.get(point.time)||[];values.push(point.value);windows.set(point.time,values)}}data.moss_points=[...windows].sort((a,b)=>a[0]-b[0]).map(([time,values])=>({time,value:values.reduce((a,b)=>a+b,0)/values.length}));data.moss_window_seconds=moss.window_seconds}catch(e){data.moss_points=[]}}if(request!==temperatureRequest)return;drawTemperature(data)}catch(e){if(request!==temperatureRequest)return;chart.replaceChildren();document.getElementById(metric+'-chart-status').textContent='Verlauf nicht erreichbar'}}
    async function updateCurrentTemperature(){try{const response=await fetch('/api/'+metric+'?current_only=true',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(metric==='moss'){const fmt=v=>v==null?'–':Number(v).toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})+' cm';document.getElementById(metric).textContent='1: '+fmt(data.current.moss1);document.getElementById(metric+'-source').textContent=['2: '+fmt(data.current.moss2)+' ╌','3: '+fmt(data.current.moss3)+' ⋯','4: '+fmt(data.current.moss4)+' – ·'].join('\\n');return}document.getElementById(metric+'').textContent=data.current.value===null?'–':data.current.value.toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})+' '+unit;document.getElementById(metric+'-source').textContent=data.current.source}catch(e){document.getElementById(metric+'').textContent='–';document.getElementById(metric+'-source').textContent='Daten nicht erreichbar'}}
    periodSelect.addEventListener('change',updateTemperature);updateTemperature();updateCurrentTemperature();setInterval(updateTemperature,30000);setInterval(updateCurrentTemperature,2000);
    }
    initMetric("temperature", "°C");initMetric("humidity", "%");initMetric("co2", "ppm");initMetric("light", "lx");initMetric("water", "cm");
    const debugToggle=document.getElementById('debug-toggle'), debugPanel=document.getElementById('debug-panel'), debugStatus=document.getElementById('debug-status');
    async function updateDebug(){if(!debugToggle.checked)return;try{const response=await fetch('/api/debug/sensors',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(!debugToggle.checked)return;debugPanel.querySelectorAll('tbody [id]').forEach(cell=>cell.textContent='–');for(const reading of data.readings){const cell=document.getElementById(`${reading.side}-${reading.sensor}-${reading.field}`);if(cell)cell.textContent=String(reading.value)}const heights=data.readings.filter(r=>/^moss[1-4]$/.test(r.side)&&r.sensor==='ultrasonic'&&r.field==='height_cm'&&Number.isFinite(r.value)).map(r=>r.value);document.getElementById('moss-average').textContent=heights.length?(heights.reduce((a,b)=>a+b,0)/heights.length).toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1})+' cm ('+heights.length+'/4)':'–';debugStatus.textContent=data.readings.length?'':'Keine aktuellen Messwerte';}catch(e){if(debugToggle.checked){debugPanel.querySelectorAll('tbody [id]').forEach(cell=>cell.textContent='–');debugStatus.textContent='Sensordaten nicht erreichbar'}}}
    debugToggle.addEventListener('change',()=>{debugPanel.hidden=!debugToggle.checked;if(debugToggle.checked)updateDebug()});setInterval(updateDebug,1000);
    const camera=document.getElementById('camera');function connectCamera(){camera.src='/camera/stream.mjpg?'+Date.now()}camera.onload=()=>document.getElementById('camera-status').textContent='Kamera: Live';camera.onerror=()=>{document.getElementById('camera-status').textContent='Kamera: Nicht erreichbar';setTimeout(connectCamera,3000)};connectCamera();
    </script></body></html>'''.replace('__WATER_OFFSET__', html.escape(setting('WATER_FLOOR_DISTANCE_CM', '8.62').replace('.', ','))))


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
