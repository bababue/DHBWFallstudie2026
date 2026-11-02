import json
import tempfile
import time
import unittest
import shutil
import subprocess
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
        self.assertIn('class="topbar"', body)
        self.assertIn('id="mode"', body)
        self.assertIn('/camera/stream.mjpg', body)
        self.assertNotIn('led-slider', body)
        self.assertIn('id="debug-toggle"', body)
        self.assertIn('id="debug-panel" hidden', body)

    @unittest.skipUnless(shutil.which('node'), 'Node.js nicht installiert')
    def test_rendered_javascript_has_valid_syntax(self):
        body = main.index().body.decode()
        script = body.split('<script>', 1)[1].split('</script>', 1)[0]
        result = subprocess.run(['node', '--check'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_maintenance_hides_current_values_but_keeps_history(self):
        record = SimpleNamespace(values={'side': 'left', 'sensor': 'sht45'},
                                 get_value=lambda: 20,
                                 get_time=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
        client = MagicMock()
        client.__enter__.return_value = client
        client.query_api.return_value.query.return_value = [SimpleNamespace(records=[record])]
        with patch.object(main, 'mode_state', return_value={'mode': 'MAINTENANCE'}), \
                patch.object(main, 'InfluxDBClient', return_value=client):
            self.assertEqual(main.debug_sensors(), {'readings': []})
            result = main.temperature('24h')
        self.assertIsNone(result['current']['value'])
        self.assertEqual(result['points'][0]['value'], 20)
        self.assertEqual(client.query_api.return_value.query.call_count, 1)

    def test_current_queries_start_at_recent_mode_transition(self):
        since = time.time() - 2
        client = MagicMock()
        client.__enter__.return_value = client
        client.query_api.return_value.query.return_value = []
        with patch.object(main, 'mode_state', return_value={'mode': 'AUTO', 'since': since}), \
                patch.object(main, 'InfluxDBClient', return_value=client):
            main.debug_sensors()
            main.temperature('1h', current_only=True)
            main.moss('1h', current_only=True)
        for call in client.query_api.return_value.query.call_args_list:
            self.assertIn('range(start: time(v:', call.args[0])
        with patch.object(main, 'mode_state', return_value={'mode': 'AUTO', 'since': since - 20}):
            self.assertEqual(main.current_range(), '-12s')

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
