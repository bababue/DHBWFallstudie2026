import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import main


class DashboardTests(unittest.TestCase):
    def test_mode_follows_sensor_state_and_expires(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'mode.json'
            with patch.object(main, 'MODE_FILE', state):
                self.assertIsNone(main.mode()['mode'])
                state.write_text(json.dumps({'mode': 'MEASURING', 'updated': time.time()}))
                self.assertEqual(main.mode()['mode'], 'MEASURING')
                state.write_text(json.dumps({'mode': 'AUTO', 'updated': time.time() - 10}))
                self.assertIsNone(main.mode()['mode'])

    def test_page_has_mode_and_camera(self):
        body = main.index().body.decode()
        self.assertIn('Aktueller Modus', body)
        self.assertIn('/camera/stream.mjpg', body)
        self.assertNotIn('led-slider', body)
        self.assertIn('id="debug-toggle"', body)
        self.assertIn('id="debug-panel" hidden', body)

    def test_debug_returns_individual_sensor_values_without_aggregation(self):
        record = SimpleNamespace(values={'side': 'left', 'sensor': 'scd40'},
                                 get_field=lambda: 'temperature_c', get_value=lambda: 21.2345)
        client = MagicMock()
        client.__enter__.return_value = client
        client.query_api.return_value.query.return_value = [SimpleNamespace(records=[record])]
        with patch.object(main, 'InfluxDBClient', return_value=client):
            result = main.debug_sensors()
        self.assertEqual(result['readings'], [{'side': 'left', 'sensor': 'scd40',
                                               'field': 'temperature_c', 'value': 21.2345}])
        query = client.query_api.return_value.query.call_args.args[0]
        self.assertIn('last()', query)
        self.assertNotIn('aggregateWindow', query)

    def test_temperature_combines_current_and_history_by_window(self):
        def record(side, sensor, value):
            return SimpleNamespace(values={'side': side, 'sensor': sensor},
                                   get_value=lambda: value,
                                   get_time=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
        table = SimpleNamespace(records=[record('left', 'sht45', 20),
                                         record('right', 'scd40', 22)])
        client = MagicMock()
        client.__enter__.return_value = client
        client.query_api.return_value.query.return_value = [table]
        with patch.object(main, 'InfluxDBClient', return_value=client):
            result = main.temperature('24h')
        self.assertEqual(result['current']['value'], 21)
        self.assertEqual(result['points'][0]['value'], 21)
        self.assertIn('(fallback)', result['points'][0]['source'])
        self.assertEqual(result['window_seconds'], 60)
        calls = client.query_api.return_value.query.call_args_list
        self.assertIn('aggregateWindow(every: 1m, fn: mean', calls[1].args[0])


if __name__ == '__main__':
    unittest.main()
