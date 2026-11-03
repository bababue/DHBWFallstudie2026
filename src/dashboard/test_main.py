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

    def test_mode_request_writes_command_and_checks_sensor_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mode-command.json'
            with patch.object(main, 'MODE_COMMAND_FILE', path), \
                    patch.object(main, 'mode_state', return_value={'mode': 'AUTO'}):
                self.assertEqual(main.request_mode({'mode': 'MAINTENANCE'}), {'requested': 'MAINTENANCE'})
                self.assertEqual(json.loads(path.read_text())['mode'], 'MAINTENANCE')
                self.assertEqual(main.request_mode({'mode': 'INVALID'}).status_code, 400)
            with patch.object(main, 'mode_state', return_value={}):
                self.assertEqual(main.request_mode({'mode': 'AUTO'}).status_code, 503)

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

    def test_actuator_changes_require_maintenance_and_show_current_values(self):
        controller = MagicMock()
        controller.status.return_value = {'fan': 20, 'pump': 0, 'led': 40}
        controller.set.return_value = {'fan': 30, 'pump': 0, 'led': 40}
        automatic = main.AutomaticControl(controller, lambda: main.mode_state().get('mode'))
        with patch.object(main, 'actuators', controller), patch.object(main, 'automatic', automatic):
            self.assertEqual(main.actuator_status()['fan'], 20)
            with patch.object(main, 'mode_state', return_value={'mode': 'AUTO'}):
                self.assertEqual(main.set_actuator('fan', {'value': 30}).status_code, 409)
                controller.set.assert_not_called()
            with patch.object(main, 'mode_state', return_value={'mode': 'MAINTENANCE'}):
                self.assertEqual(main.set_actuator('fan', {'value': 30})['fan'], 30)
                controller.set.assert_called_once_with('fan', 30)
        with patch.object(main, 'actuators', None):
            self.assertEqual(main.actuator_status().status_code, 503)

    def test_water_lock_uses_fresh_raw_distance_and_margin(self):
        water = {'sensor_boden_abstand_cm': 8.265, 'max_fuellhoehe_cm': 6.0,
                 'sicherheitsabstand_cm': 1.0}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'water.json'
            with patch.object(main, 'WATER_SAFETY_FILE', path), \
                    patch.object(main, 'load', return_value={'wasserstand': water}):
                self.assertFalse(main.water_pump_allowed())
                for distance, age, allowed in [(4.0, 0, True), (3.265, 0, False),
                                               (2.0, 0, False), (None, 0, False),
                                               (float('nan'), 0, False), (4.0, 4, False)]:
                    path.write_text(json.dumps({'sampled': time.time() - age, 'distance_cm': distance}))
                    self.assertEqual(main.water_pump_allowed(), allowed, (distance, age))
                water['max_fuellhoehe_cm'] = None
                self.assertFalse(main.water_pump_allowed())

    def test_live_readings_expire_and_debug_uses_them(self):
        now = time.time()
        readings = [dict(side='left', sensor='sht45', field='temperature_c', value=21, sampled=now),
                    dict(side='right', sensor='sht45', field='temperature_c', value=99, sampled=now - 13)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'readings.json'
            path.write_text(json.dumps({'updated': now, 'readings': readings}))
            with patch.object(main, 'READINGS_FILE', path):
                self.assertEqual(main.debug_sensors()['readings'], readings[:1])
                path.write_text(json.dumps({'updated': now - 6, 'readings': readings}))
                self.assertEqual(main.live_readings(), [])

    def test_maintenance_shows_live_values_and_no_history(self):
        readings = [dict(side='left', sensor='sht45', field='temperature_c', value=21),
                    dict(side='right', sensor='sht45', field='temperature_c', value=23),
                    dict(side='moss1', sensor='ultrasonic', field='height_cm', value=2)]
        with patch.object(main, 'mode_state', return_value={'mode': 'MAINTENANCE'}), \
                patch.object(main, 'live_readings', return_value=readings), \
                patch.object(main, 'InfluxDBClient') as client:
            self.assertEqual(main.debug_sensors()['readings'], readings)
            self.assertEqual(main.temperature('24h')['current']['value'], 22)
            self.assertEqual(main.temperature('24h')['points'], [])
            self.assertEqual(main.moss('24h')['current'], {'moss1': 2})
            client.assert_not_called()
        body = main.index().body.decode()
        self.assertIn('content:"Datenmessung pausiert"', body)
        self.assertIn('.chart-container{position:relative;height:230px}', body)

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
        readings = [dict(side='left', sensor='sht45', field='temperature_c', value=20),
                    dict(side='right', sensor='scd40', field='temperature_c', value=22)]
        with patch.object(main, 'InfluxDBClient', return_value=client), \
                patch.object(main, 'live_readings', return_value=readings), \
                patch.object(main, 'mode_state', return_value={'mode': 'AUTO'}):
            result = main.temperature('24h')
        self.assertEqual(result['current']['value'], 21)
        self.assertEqual(result['points'][0]['value'], 21)
        self.assertIn('(fallback)', result['points'][0]['source'])
        self.assertEqual(result['window_seconds'], 60)
        calls = client.query_api.return_value.query.call_args_list
        self.assertIn('aggregateWindow(every: 1m, fn: mean', calls[0].args[0])


if __name__ == '__main__':
    unittest.main()
