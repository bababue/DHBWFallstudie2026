"""Dashboard for the current operating mode and camera."""
import json
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse

app = FastAPI(title="Moos Dashboard")
MODE_FILE = Path('/run/moos/mode.json')


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
    return HTMLResponse('''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Moos Dashboard</title><style>
    *{box-sizing:border-box}body{margin:0;background:#eff3ec;color:#213a2c;font:16px system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:clamp(24px,5vw,64px)}header{margin-bottom:36px}header p,.label{color:#61796a;font-size:.8rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase}h1{font-size:clamp(2rem,5vw,3.5rem);margin:.25em 0}.grid{display:grid;grid-template-columns:1fr 1.3fr;gap:20px}.card{background:white;border:1px solid #dce6d9;border-radius:20px;padding:28px;box-shadow:0 8px 28px #233b2910}.mode{display:flex;flex-direction:column;justify-content:space-between;min-height:310px}.mode strong{font-size:clamp(2rem,4vw,3.5rem);overflow-wrap:anywhere}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#76a77a;margin-right:8px}.camera img{display:block;width:100%;aspect-ratio:16/9;object-fit:contain;background:#1c3024;border-radius:12px}.status{color:#61796a;font-size:.9rem}@media(max-width:700px){.grid{grid-template-columns:1fr}.mode{min-height:220px}}
    </style></head><body><main><header><p>Moos Projekt</p><h1>Übersicht</h1></header><div class="grid"><section class="card mode"><div><span class="label">Aktueller Modus</span></div><strong id="mode">Verbinde …</strong><p class="status" id="mode-status">Modus wird geladen</p></section><section class="card camera"><p class="label">Kamera</p><img id="camera" alt="Kamerafeed"><p class="status" id="camera-status">Verbinde …</p></section></div></main><script>
    async function updateMode(){try{const response=await fetch('/api/mode',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();document.getElementById('mode').textContent=data.mode||'Nicht verfügbar';document.getElementById('mode-status').textContent=data.mode?'Aktueller Betriebsmodus':'Verbindung zum Sensorprozess fehlt';}catch(e){document.getElementById('mode').textContent='Nicht verfügbar';document.getElementById('mode-status').textContent='Verbindung zum Dashboard fehlt';}}updateMode();setInterval(updateMode,1000);
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
