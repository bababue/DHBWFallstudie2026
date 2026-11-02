"""Accept complete OLED frames from the display container on a Unix socket."""

import logging
import os
import socketserver
from threading import Thread

from oled import BREITE, HOEHE, Oled


LOG = logging.getLogger("moos.oled_bridge")
SOCKET_PATH = "/run/moos-oled/frame.sock"
FRAME_BYTES = BREITE * HOEHE // 8


class FrameHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(3)
        frame = bytearray()
        while len(frame) < FRAME_BYTES:
            chunk = self.request.recv(FRAME_BYTES - len(frame))
            if not chunk:
                return
            frame.extend(chunk)
        with self.server.bus_lock:
            self.server.oled.zeigen(frame)
        self.request.sendall(b"\x01")


class FrameServer(socketserver.UnixStreamServer):
    def __init__(self, bus, bus_lock):
        os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        super().__init__(SOCKET_PATH, FrameHandler)
        self.bus_lock = bus_lock
        self.oled = Oled(bus)
        os.chmod(SOCKET_PATH, 0o666)
        self.thread = Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=3)
        try:
            with self.bus_lock:
                self.oled.ausschalten()
        except Exception as error:
            LOG.warning("OLED shutdown failed: %s", error)
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
