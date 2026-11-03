#!/usr/bin/env python3
"""Live-View der Pi-Kamera (CAM0) als MJPEG-Stream im Browser.

Nutzt nur rpicam-vid und die Python-Standardbibliothek. Die Kamera läuft nur,
solange mindestens ein Browser zuschaut, und wird danach wieder freigegeben.
"""

import os
import subprocess
import threading
from http import server

PORT = int(os.environ.get("KAMERA_PORT", "8000"))
BREITE = 1280
HOEHE = 720
FPS = 10
QUALITAET = 60
# Nach dem letzten Zuschauer noch kurz weiterlaufen, damit ein Neuladen der Seite
# nicht jedes Mal einen Kamera-Neustart auslöst.
NACHLAUF_S = 10

RPICAM_CMD = [
    "rpicam-vid", "-t", "0", "-n",
    "--codec", "mjpeg", "-q", str(QUALITAET),
    "--width", str(BREITE), "--height", str(HOEHE), "--framerate", str(FPS),
    "--mode", "2304:1296",  # voller Bildwinkel der imx708, gebinnt
    "--autofocus-mode", "continuous",
    "-o", "-",
]

JPEG_ENDE = b"\xff\xd9"

SEITE = f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Moos Kamera</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #111; color: #ddd;
    font: 14px/1.4 system-ui, sans-serif; }}
  body {{ display: flex; flex-direction: column; }}
  header {{ display: flex; align-items: center; gap: 8px; padding: 10px 16px; }}
  .punkt {{ width: 10px; height: 10px; border-radius: 50%; background: #666; }}
  .punkt.live {{ background: #e5484d; }}
  main {{ flex: 1; min-height: 0; display: flex; align-items: center;
    justify-content: center; padding: 0 16px 16px; }}
  img {{ max-width: 100%; max-height: 100%; object-fit: contain; background: #000; }}
</style>
</head>
<body>
<header><span class="punkt" id="punkt"></span><strong>Moos Kamera</strong>
<span id="status">verbinde…</span></header>
<main><img id="bild" alt="Live-Bild der Kamera" width="{BREITE}" height="{HOEHE}"></main>
<script>
  const bild = document.getElementById("bild");
  const punkt = document.getElementById("punkt");
  const status = document.getElementById("status");
  function verbinden() {{ bild.src = "/stream.mjpg?" + Date.now(); }}
  bild.onload = () => {{ punkt.classList.add("live"); status.textContent = "live"; }};
  bild.onerror = () => {{
    punkt.classList.remove("live");
    status.textContent = "getrennt – neuer Versuch…";
    setTimeout(verbinden, 2000);
  }};
  verbinden();
</script>
</body>
</html>
""".encode("utf-8")


class Kamera:
    """Startet rpicam-vid bei Bedarf und verteilt das jeweils neueste JPEG."""

    def __init__(self):
        self._lock = threading.Lock()
        self._neues_bild = threading.Condition()
        self._bild = None
        self._bild_nr = 0
        self._zuschauer = 0
        self._proc = None
        self._stopp_timer = None

    def anmelden(self):
        with self._lock:
            self._zuschauer += 1
            if self._stopp_timer:
                self._stopp_timer.cancel()
                self._stopp_timer = None
            if self._proc is None or self._proc.poll() is not None:
                self._starten()

    def abmelden(self):
        with self._lock:
            self._zuschauer -= 1
            if self._zuschauer == 0:
                self._stopp_timer = threading.Timer(NACHLAUF_S, self._stoppen_falls_leer)
                self._stopp_timer.daemon = True
                self._stopp_timer.start()

    def warte_auf_bild(self, letzte_nr, timeout=10):
        """Liefert (nr, jpeg) des nächsten Bilds oder None, wenn keins kommt."""
        with self._neues_bild:
            if not self._neues_bild.wait_for(
                lambda: self._bild is not None and self._bild_nr != letzte_nr, timeout
            ):
                return None
            return self._bild_nr, self._bild

    def _starten(self):
        print("Kamera startet", flush=True)
        self._proc = subprocess.Popen(
            RPICAM_CMD, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
        )
        threading.Thread(target=self._lesen, args=(self._proc,), daemon=True).start()

    def _stoppen_falls_leer(self):
        with self._lock:
            if self._zuschauer == 0 and self._proc is not None:
                print("Kamera stoppt (keine Zuschauer)", flush=True)
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                self._proc = None
                with self._neues_bild:
                    self._bild = None

    def _lesen(self, proc):
        # rpicam-vid schreibt die JPEGs direkt hintereinander. FF D9 kann in
        # JPEG-Daten nur als Endmarker vorkommen, daran wird getrennt.
        puffer = b""
        while True:
            daten = proc.stdout.read(65536)
            if not daten:
                break
            puffer += daten
            while True:
                ende = puffer.find(JPEG_ENDE)
                if ende < 0:
                    break
                jpeg, puffer = puffer[: ende + 2], puffer[ende + 2 :]
                start = jpeg.find(b"\xff\xd8")
                if start < 0:
                    continue
                with self._neues_bild:
                    self._bild = jpeg[start:]
                    self._bild_nr += 1
                    self._neues_bild.notify_all()


kamera = Kamera()


class Handler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        pfad = self.path.split("?", 1)[0]
        if pfad == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(SEITE)))
            self.end_headers()
            self.wfile.write(SEITE)
        elif pfad == "/stream.mjpg":
            self._stream()
        else:
            self.send_error(404)

    def _stream(self):
        self.send_response(200)
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
        self.end_headers()
        kamera.anmelden()
        nr = None
        try:
            while True:
                ergebnis = kamera.warte_auf_bild(nr)
                if ergebnis is None:
                    break
                nr, jpeg = ergebnis
                self.wfile.write(b"--FRAME\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            kamera.abmelden()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    httpd = server.ThreadingHTTPServer(("", PORT), Handler)
    httpd.daemon_threads = True
    print(f"Live-View läuft auf Port {PORT}", flush=True)
    httpd.serve_forever()
