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
                state.write_text(json.dumps({'mode': 'MANUAL', 'session': 'one', 'updated': time.time()}))
                self.assertEqual(main.mode()['mode'], 'MANUAL')
                state.write_text(json.dumps({'mode': 'AUTO', 'session': 'one', 'updated': time.time() - 10}))
                self.assertIsNone(main.mode()['mode'])

    def test_mode_request_writes_command_and_checks_sensor_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mode-command.json'
            with patch.object(main, 'MODE_COMMAND_FILE', path), \
                    patch.object(main, 'mode_state', return_value={'mode': 'AUTO'}):
                self.assertEqual(main.request_mode({'mode': 'MANUAL'}), {'requested': 'MANUAL'})
                self.assertEqual(json.loads(path.read_text())['mode'], 'MANUAL')
                self.assertEqual(main.request_mode({'mode': 'INVALID'}).status_code, 400)
            with patch.object(main, 'mode_state', return_value={}):
                self.assertEqual(main.request_mode({'mode': 'AUTO'}).status_code, 503)

    def test_page_has_mode_and_camera(self):
        body = main.index().body.decode()
        self.assertIn('class="topbar"', body)
        self.assertIn('id="mode"', body)
        script = (Path(main.__file__).parent / 'static' / 'app.js').read_text()
        self.assertIn('/camera/stream.mjpg', script)
        self.assertNotIn('led-slider', body)
        self.assertIn('id="debug-toggle"', body)
        self.assertIn('id="debug-panel" hidden', body)
        self.assertIn('id="auto-actuators"', body)
        self.assertIn('id="manual-actuators"', body)
        self.assertIn('id="light-timeline"', body)

    @unittest.skipUnless(shutil.which('node'), 'Node.js nicht installiert')
    def test_rendered_javascript_has_valid_syntax(self):
        body = main.index().body.decode()
        script = (Path(main.__file__).parent / 'static' / 'app.js').read_text()
        result = subprocess.run(['node', '--check'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actuator_changes_require_manual_and_show_current_values(self):
        controller = MagicMock()
        controller.status.return_value = {'fan': 20, 'pump': 0, 'led': 40}
        controller.set.return_value = {'fan': 30, 'pump': 0, 'led': 40}
        automatic = main.AutomaticControl(controller, lambda: main.mode_state())
        with patch.object(main, 'actuators', controller), patch.object(main, 'automatic', automatic):
            self.assertEqual(main.actuator_status()['fan'], 20)
            with patch.object(main, 'mode_state', return_value={'mode': 'AUTO'}):
                self.assertEqual(main.set_actuator('fan', {'value': 30}).status_code, 409)
                controller.set.assert_not_called()
            with patch.object(main, 'mode_state', return_value={'mode': 'MANUAL'}):
                automatic.initialize_manual()
                controller.set.reset_mock()
                self.assertEqual(main.set_actuator('fan', {'value': 30})['fan'], 30)
                controller.set.assert_called_once_with('fan', 30)
        with patch.object(main, 'actuators', None):
            self.assertEqual(main.actuator_status().status_code, 503)

    def test_water_lock_uses_fresh_raw_distance_and_hard_limit(self):
        water = {'sensor_boden_abstand_cm': 8.265, 'max_fuellhoehe_cm': 5.0}
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

    def test_water_state_uses_direct_ceiling_distances_and_one_water_snapshot(self):
        from test_pump_control import CONFIG, readings
        config = dict(CONFIG, wasserstand=dict(CONFIG['wasserstand'], sensor_boden_abstand_cm=8.265))
        now = time.time()
        with patch.object(main, 'water_snapshot', return_value={'sampled': now, 'distance_cm': 4.0,
                                'water_level_cm': 4.265, 'measurement_stable': 1}), \
                patch.object(main, 'live_readings', return_value=readings(now)):
            state = main.pump_state(config)
        self.assertAlmostEqual(state['target_cm'], 5.0)
        self.assertTrue(state['water_ready'])
        self.assertTrue(state['pump_allowed'])
        self.assertEqual(state['moss_distances_cm']['moss1'], 5.6)

    def test_water_api_only_reads_controller_snapshot(self):
        control = MagicMock()
        control.status.return_value = {'pump_enabled': False, 'target_cm': 5}
        with patch.object(main, 'automatic', control), patch.object(main, 'pump_state', side_effect=AssertionError):
            self.assertEqual(main.automatic_water(), control.status.return_value)
        control.apply.assert_not_called()

    def test_enable_endpoint_requires_boolean_and_passes_current_confirmation(self):
        control = MagicMock()
        control.set_pump_enabled.return_value = {'pump_enabled': True}
        with patch.object(main, 'automatic', control):
            self.assertEqual(main.enable_pump({'enabled': 'true'}).status_code, 400)
            self.assertEqual(main.enable_pump({'enabled': True, 'confirmation': 'current'}), {'pump_enabled': True})
            control.set_pump_enabled.assert_called_once_with(True, 'current')
            control.set_pump_enabled.side_effect = ValueError('stale')
            self.assertEqual(main.enable_pump({'enabled': True, 'confirmation': 'old'}).status_code, 409)

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

    def test_ultrasonic_debug_uses_fresh_filtered_readings_and_mounting_heights(self):
        config = main.load()
        now = 100
        def reading(side, field, value, sampled=now):
            return dict(side=side, sensor='ultrasonic', field=field, value=value, sampled=sampled)
        data = [reading('tank', 'distance_cm', 4.0),
                reading('tank', 'distance_filtered_cm', 4.1),
                reading('tank', 'distance_inlier_percent', 75),
                reading('tank', 'measurement_stable', 1),
                reading('tank', 'water_level_cm', 4.165),
                reading('moss1', 'distance_cm', 5.1),
                reading('moss1', 'distance_filtered_cm', 5.2),
                reading('moss1', 'distance_inlier_percent', 65),
                reading('moss1', 'measurement_stable', 1),
                reading('moss2', 'distance_cm', 4.0, 80),
                reading('moss2', 'distance_filtered_cm', 4.1, 80),
                reading('moss2', 'measurement_stable', 1, 80),
                reading('moss3', 'distance_cm', 5),
                reading('moss3', 'distance_filtered_cm', 5),
                reading('moss3', 'measurement_stable', 1),
                reading('moss4', 'distance_cm', 5),
                reading('moss4', 'distance_filtered_cm', 4.9),
                reading('moss4', 'distance_inlier_percent', 0),
                reading('moss4', 'measurement_stable', 0)]
        with patch.object(main, 'live_readings', return_value=data), \
                patch.object(main, 'load', return_value=config), \
                patch.object(main.time, 'time', return_value=now):
            debug = main.debug_sensors()
            result = debug['ultrasonic']
        self.assertEqual(result['tank'], dict(raw_cm=4, filtered_cm=4.1,
                                              inlier_percent=75, calculated_cm=4.165))
        self.assertAlmostEqual(result['moss1']['calculated_cm'], config['moos']['montagehoehe_cm'] - 5.2)
        self.assertEqual(result['moss1']['inlier_percent'], 65)
        self.assertEqual(result['moss2'], dict(raw_cm=None, filtered_cm=None,
                                               inlier_percent=None, calculated_cm=None))
        self.assertAlmostEqual(result['moss3']['calculated_cm'], config['moos']['montagehoehe_cm'] - 5)
        self.assertEqual(result['moss4'], dict(raw_cm=5, filtered_cm=None,
                                               inlier_percent=0, calculated_cm=None))
        self.assertAlmostEqual(debug['moss_median_cm'], config['moos']['montagehoehe_cm'] - 5.1)

    def test_ultrasonic_debug_uses_one_shared_mounting_height(self):
        config = main.load()
        config['moos']['montagehoehe_cm'] = None
        data = [dict(side='moss1', sensor='ultrasonic', field=field, value=value, sampled=100)
                for field, value in [('distance_cm', 5), ('distance_filtered_cm', 5), ('measurement_stable', 1)]]
        with patch.object(main, 'live_readings', return_value=data), \
                patch.object(main, 'load', return_value=config), patch.object(main.time, 'time', return_value=100):
            result = main.debug_sensors()
        self.assertIsNone(result['moss_mounting_height_cm'])
        self.assertIsNone(result['ultrasonic']['moss1']['calculated_cm'])
        self.assertIsNone(result['moss_median_cm'])

    def test_ultrasonic_debug_does_not_mix_old_water_or_inconsistent_samples(self):
        now = 100
        data = [dict(side='tank', sensor='ultrasonic', field=field, value=value, sampled=sampled)
                for field, value, sampled in [('distance_cm', 4, 96), ('distance_filtered_cm', 4, 96),
                                              ('measurement_stable', 1, 96), ('water_level_cm', 4, 96)]]
        data += [dict(side='moss1', sensor='ultrasonic', field=field, value=value, sampled=sampled)
                 for field, value, sampled in [('distance_cm', 5, 100), ('distance_filtered_cm', 5, 99),
                                               ('measurement_stable', 1, 100)]]
        with patch.object(main, 'live_readings', return_value=data), patch.object(main.time, 'time', return_value=now):
            result = main.debug_sensors()['ultrasonic']
        self.assertEqual(result['tank'], dict(raw_cm=None, filtered_cm=None,
                                              inlier_percent=None, calculated_cm=None))
        self.assertEqual(result['moss1'], dict(raw_cm=5, filtered_cm=None,
                                               inlier_percent=None, calculated_cm=None))

    def test_ultrasonic_debug_distinguishes_missing_echo_from_no_recent_sample(self):
        now = 100
        data = [dict(side='left', sensor='sht45', field='temperature_c', value=22, sampled=now),
                dict(side='tank', sensor='ultrasonic', field='echo_received', value=0, sampled=now),
                dict(side='moss1', sensor='ultrasonic', field='echo_received', value=0, sampled=now),
                dict(side='moss2', sensor='ultrasonic', field='echo_received', value=0, sampled=80),
                dict(side='moss3', sensor='ultrasonic', field='distance_cm', value=5.3, sampled=now),
                dict(side='moss3', sensor='ultrasonic', field='echo_received', value=1, sampled=now)]
        with patch.object(main, 'live_readings', return_value=data), patch.object(main.time, 'time', return_value=now):
            result = main.debug_sensors()
        self.assertEqual(result['ultrasonic_status']['tank'], 'invalid')
        self.assertEqual(result['ultrasonic_status']['moss1'], 'invalid')
        self.assertEqual(result['ultrasonic_status']['moss2'], 'unavailable')
        self.assertEqual(result['ultrasonic_status']['moss3'], 'ok')
        self.assertEqual(result['ultrasonic']['moss3']['raw_cm'], 5.3)
        self.assertIsNone(result['ultrasonic']['moss3']['filtered_cm'])

    def test_ultrasonic_debug_reports_configured_filter(self):
        config = main.load()
        config['ultraschall_glaettung'].update(messungen=60,
                                                wasser_streuung_cm=.4, moos_streuung_cm=.6, max_messpause_s=8)
        with patch.object(main, 'live_readings', return_value=[]), patch.object(main, 'load', return_value=config):
            info = main.debug_sensors()['filter']
        self.assertEqual(info, {'samples': 60, 'max_gap_seconds': 8,
                                'water_spread_cm': .4, 'moss_spread_cm': .6})

    def test_manual_shows_live_values_and_history(self):
        readings = [dict(side='left', sensor='sht45', field='temperature_c', value=21)]
        record = SimpleNamespace(values={'side': 'left', 'sensor': 'sht45'},
                                 get_value=lambda: 20,
                                 get_time=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
        client = MagicMock()
        client.__enter__.return_value = client
        client.query_api.return_value.query.return_value = [SimpleNamespace(records=[record])]
        with patch.object(main, 'mode_state', return_value={'mode': 'MANUAL'}), \
                patch.object(main, 'live_readings', return_value=readings), \
                patch.object(main, 'InfluxDBClient', return_value=client):
            result = main.temperature('24h')
        self.assertEqual(result['current']['value'], 21)
        self.assertEqual(result['points'][0]['value'], 20)
        self.assertNotIn('Datenmessung pausiert', main.index().body.decode())

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

    def test_ultrasonic_history_returns_one_median_height_series(self):
        def record(side, value, hour):
            return SimpleNamespace(values={'side': side}, get_value=lambda: value,
                                   get_time=lambda: datetime(2026, 1, 1, hour, tzinfo=timezone.utc))
        table = SimpleNamespace(records=[record('moss1', 5.6, 2), record('tank', 4.2, 0),
                                         record('moss1', 5.5, 1), record('moss1', 5, 0),
                                         record('moss2', 5.7, 0),
                                         record('moss3', 5.8, 0), record('moss4', 5.9, 0),
                                         record('other', 7, 0), record('tank', float('nan'), 1)])
        client = MagicMock()
        client.__enter__.return_value = client
        client.query_api.return_value.query.return_value = [table]
        config = main.load()
        config['moos']['montagehoehe_cm'] = 10
        with patch.object(main, 'InfluxDBClient', return_value=client), \
                patch.object(main, 'load', return_value=config):
            result = main.ultrasonic_history('1h')
            short = main.ultrasonic_history('10m')
            config['moos']['montagehoehe_cm'] = None
            without_mount = main.ultrasonic_history('1h')
        self.assertEqual(list(result['series']), ['moss_median'])
        self.assertEqual([point['value'] for point in result['series']['moss_median']], [4.25, 4.5, 4.4])
        self.assertEqual(result['window_seconds'], 10)
        query = client.query_api.return_value.query.call_args.args[0]
        self.assertIn('r._field == "distance_filtered_cm"', query)
        self.assertIn('fn: last', query)
        self.assertNotIn('water_level_cm', query)
        self.assertNotIn('r._field == "distance_cm"', query)
        self.assertEqual(short['window_seconds'], 4)
        self.assertEqual(without_mount['series']['moss_median'], [])
        self.assertEqual(main.ultrasonic_history('invalid').status_code, 400)


if __name__ == '__main__':
    unittest.main()
