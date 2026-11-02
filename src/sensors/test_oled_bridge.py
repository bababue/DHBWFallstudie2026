"""The OLED process must send frames without claiming the sensor bus."""

import unittest
from threading import Lock

from oled import Oled
from oled_bridge import FRAME_BYTES, FrameHandler


class OledBridgeTests(unittest.TestCase):
    def test_accepts_one_complete_frame_and_acknowledges_it(self):
        class Bus:
            def __init__(self):
                self.writes = []

            def write(self, address, payload):
                self.writes.append((address, payload))

        class Request:
            def __init__(self, frame):
                self.frame = frame
                self.ack = b""

            def settimeout(self, seconds):
                pass

            def recv(self, count):
                chunk, self.frame = self.frame[:count], self.frame[count:]
                return chunk

            def sendall(self, data):
                self.ack += data

        bus = Bus()
        request = Request(bytes(FRAME_BYTES))
        server = type("Server", (), {"bus_lock": Lock(), "oled": Oled(bus)})()
        FrameHandler(request, ("local",), server)
        self.assertEqual(request.ack, b"\x01")
        self.assertTrue(bus.writes)
        self.assertTrue(all(address == 0x3C for address, _ in bus.writes))


if __name__ == "__main__":
    unittest.main()
