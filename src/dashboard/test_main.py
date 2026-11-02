import unittest
import json
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import WebSocketDisconnect

from main import DISPLAY_ROWS, Hub, READINGS, Settings, make_payload, read_latest, render_page, sensor_stream


class DashboardTests(unittest.TestCase):
    def test_plain_page_contains_every_sensor_value(self):
        page = render_page()
        self.assertEqual(page.count("<tr><td>"), len(DISPLAY_ROWS))
        self.assertIn("<th>Messwert</th><th>Sensor</th><th>Links</th><th>Rechts</th>", page)
        self.assertIn('<tr><td>CO₂</td><td>SCD40</td><td id="left-scd40-co2_ppm">', page)
        self.assertLess(page.index("<td>Temperatur</td>"), page.index("<td>Luftfeuchte</td>"))
        self.assertLess(page.index("<td>Luftfeuchte</td>"), page.index("<td>Licht</td>"))
        self.assertLess(page.index("<td>Licht</td>"), page.index("<td>CO₂</td>"))
        for reading in READINGS:
            self.assertIn(f'id="{reading.side}-{reading.sensor}-{reading.field}"', page)
        self.assertIn('new WebSocket(`${protocol}//${location.host}/ws`)', page)
        self.assertNotIn('http-equiv="refresh"', page)
        self.assertNotIn("<style", page)
        self.assertNotIn("stylesheet", page)
        self.assertIn('id="camera"', page)
        self.assertIn('id="led-slider"', page)
        self.assertIn('id="fan-slider"', page)
        self.assertIn('stream.mjpg', page)

    def test_payload_formats_live_values_and_missing_values(self):
        payload = make_payload({("left", "scd40", "co2_ppm"): 512.0})
        self.assertEqual(payload["readings"]["left-scd40-co2_ppm"], "512 ppm")
        self.assertEqual(payload["readings"]["right-bh1750-illuminance_lux"], "kein aktueller Wert")
        self.assertEqual(len(payload["readings"]), len(READINGS))
        self.assertFalse(payload["controls_enabled"])

    def test_queries_recent_raw_points_and_maps_tags(self):
        record = SimpleNamespace(
            values={"side": "right", "sensor": "sht45"},
            get_field=lambda: "temperature_c",
            get_value=lambda: 21.25,
        )
        client = unittest.mock.MagicMock()
        client.__enter__.return_value = client
        client.query_api.return_value.query.return_value = [SimpleNamespace(records=[record])]
        settings = Settings("http://influxdb:8086", "moos", "moos_sensors", "test-token", 2, 180, 8000, False, "")
        with patch("main.InfluxDBClient", return_value=client):
            values = read_latest(settings)
        self.assertEqual(values[("right", "sht45", "temperature_c")], 21.25)
        query = client.query_api.return_value.query.call_args.args[0]
        self.assertIn('range(start: -180s)', query)
        self.assertIn('last()', query)
        self.assertNotIn('aggregateWindow', query)


class WebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_snapshot_on_connection_and_removes_closed_client(self):
        hub = Hub()
        hub.snapshot = make_payload({("left", "scd40", "co2_ppm"): 512.0})

        class FakeSocket:
            app = SimpleNamespace(state=SimpleNamespace(
                hub=hub, settings=Settings("", "", "", "token", 2, 180, 8000, False, "")))

            def __init__(self):
                self.accepted = False
                self.messages = []

            async def accept(self):
                self.accepted = True

            async def send_json(self, message):
                self.messages.append(message)

            async def receive_text(self):
                raise WebSocketDisconnect(code=1000)

        socket = FakeSocket()
        await sensor_stream(socket)
        self.assertTrue(socket.accepted)
        self.assertEqual(socket.messages, [hub.snapshot])
        self.assertNotIn(socket, hub.clients)

    async def test_broadcasts_only_changed_values(self):
        hub = Hub()
        messages = []

        class FakeSocket:
            async def send_json(self, message):
                messages.append(message)

        hub.clients.add(FakeSocket())
        payload = make_payload({("right", "sht45", "temperature_c"): 21.5})
        await hub.publish(payload)
        await hub.publish(payload)
        self.assertEqual(messages, [payload])

    async def test_password_protects_slider_commands(self):
        class FakeActuators:
            def __init__(self):
                self.values = {"led": 0, "fan": 0}

            def status(self):
                return dict(self.values)

            def set(self, device, value):
                self.values[device] = value
                return self.status()

        actuators = FakeActuators()
        hub = Hub(actuators)
        settings = Settings("", "", "", "token", 2, 180, 8000, True, "correct")

        class FakeSocket:
            app = SimpleNamespace(state=SimpleNamespace(hub=hub, settings=settings))

            def __init__(self):
                self.messages = []
                self.commands = iter([
                    json.dumps({"type": "set", "device": "led", "value": 50, "password": "wrong"}),
                    json.dumps({"type": "set", "device": "led", "value": 50, "password": "correct"}),
                ])

            async def accept(self):
                pass

            async def send_json(self, message):
                self.messages.append(message)

            async def receive_text(self):
                try:
                    return next(self.commands)
                except StopIteration:
                    raise WebSocketDisconnect(code=1000)

        socket = FakeSocket()
        await sensor_stream(socket)
        self.assertEqual(actuators.status()["led"], 50)
        self.assertIn({"message": "Falsches Steuerpasswort"}, socket.messages)
        self.assertEqual(socket.messages[-1]["controls"], {"led": 50, "fan": 0})


if __name__ == "__main__":
    unittest.main()
