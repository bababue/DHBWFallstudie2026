import copy
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
from automatic import AutomaticControl, light_schedule, auto_setpoints
from configuration import load
from test_pump_control import state


class Actuator:
    def __init__(self):
        self.values = dict(fan=0, pump=0, led=0)
        self.allowed = True
    def status(self): return dict(self.values)
    def set(self, device, value):
        self.values[device] = value
        return self.status()
    def pump_allowed(self): return self.allowed


class AutomaticControlTests(unittest.TestCase):
    def setUp(self):
        self.mode = {'mode': 'AUTO', 'session': 'first'}
        self.data = state()
        self.config = copy.deepcopy(load())
        self.actuator = Actuator()
        self.control = self.make_control()
        self.now = 0
        patcher = patch('automatic.load', side_effect=lambda: self.config)
        patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch('automatic.time.monotonic', side_effect=lambda: self.now)
        patcher.start(); self.addCleanup(patcher.stop)

    def make_control(self):
        return AutomaticControl(self.actuator, lambda: dict(self.mode), lambda config: dict(self.data))

    def arm(self):
        self.control.apply()
        token = self.control.status()['confirmation']
        self.control.set_pump_enabled(True, token)
        return token

    def test_auto_starts_blocked_and_needs_explicit_current_confirmation(self):
        self.control.apply()
        self.now = 100
        self.control.apply()
        self.assertEqual(self.actuator.values['pump'], 0)
        with self.assertRaises(ValueError): self.control.set_pump_enabled(True, 'old-token')
        self.arm()
        self.now += 30
        self.control.apply()
        self.assertEqual(self.actuator.values['pump'], 25)
        self.control.set_pump_enabled(False, None)
        self.assertEqual(self.actuator.values['pump'], 0)
        self.assertFalse(self.control.enabled)

    def test_mode_switch_and_quick_return_need_new_confirmation(self):
        old = self.arm()
        self.mode = {'mode': 'MANUAL', 'session': 'manual'}
        self.control.apply()
        self.assertFalse(self.control.enabled)
        self.mode = {'mode': 'AUTO', 'session': 'again'}
        self.control.apply()
        self.assertFalse(self.control.enabled)
        with self.assertRaises(ValueError): self.control.set_pump_enabled(True, old)
        self.arm()
        # Intermediate MANUAL need not have been observed by the dashboard loop.
        self.mode['session'] = 'quick-manual-auto'
        self.control.apply()
        self.assertFalse(self.control.enabled)

    def test_sensor_restart_dashboard_restart_and_connection_loss_revoke_release(self):
        self.arm()
        self.mode['session'] = 'restarted-sensor'
        self.control.apply()
        self.assertFalse(self.control.enabled)
        old = self.arm()
        replacement = self.make_control()
        replacement.apply()
        with self.assertRaises(ValueError): replacement.set_pump_enabled(True, old)
        self.mode = {}
        self.control.apply()
        self.assertFalse(self.control.enabled)
        self.assertEqual(self.actuator.values['pump'], 0)

    def test_config_change_rejects_dialog_opened_before_change(self):
        self.control.apply()
        token = self.control.status()['confirmation']
        self.config['automatik']['wasser_unter_moosspitzen_cm'] = 3
        with self.assertRaises(ValueError): self.control.set_pump_enabled(True, token)
        self.assertFalse(self.control.enabled)

    def test_switch_off_stops_running_pump_and_invalidates_old_confirmation(self):
        old = self.arm()
        self.now = 30
        self.control.apply()
        self.assertEqual(self.actuator.values['pump'], 25)
        self.control.set_pump_enabled(False, None)
        self.assertEqual(self.actuator.values['pump'], 0)
        with self.assertRaises(ValueError): self.control.set_pump_enabled(True, old)

    def test_new_mode_session_stops_a_running_pump_immediately(self):
        self.arm()
        self.now = 30
        self.control.apply()
        self.assertEqual(self.actuator.values['pump'], 25)
        self.mode['session'] = 'new-auto'
        self.control.apply()
        self.assertEqual(self.actuator.values['pump'], 0)
        self.assertFalse(self.control.enabled)

    def test_heartbeat_refresh_does_not_revoke_current_session(self):
        self.mode['updated'] = 0
        self.arm()
        self.mode['updated'] = 1
        self.now = 30
        self.control.apply()
        self.assertTrue(self.control.enabled)
        self.assertEqual(self.actuator.values['pump'], 25)

    def test_control_error_and_shutdown_revoke_release_and_stop_outputs(self):
        self.arm()
        self.now = 30
        self.control.apply()
        with patch.object(self.control, 'get_water_state', side_effect=OSError('snapshot unavailable')):
            with self.assertRaises(OSError): self.control.apply()
        self.assertFalse(self.control.enabled)
        self.assertEqual(self.actuator.values['pump'], 0)
        self.arm()
        self.control.close()
        self.assertFalse(self.control.enabled)
        self.assertEqual(self.actuator.values['pump'], 0)

    def test_status_is_read_only_and_unsafe_readings_cannot_be_armed(self):
        self.control.apply()
        token = self.control.status()['confirmation']
        self.data['water_ready'] = False
        with self.assertRaises(ValueError): self.control.set_pump_enabled(True, token)
        self.assertFalse(self.control.enabled)
        context = self.control.context
        self.control.status(); self.control.status()
        self.assertEqual(self.control.context, context)

    def test_manual_remains_manual_and_water_lock_still_stops_it(self):
        self.mode = {'mode': 'MANUAL', 'session': 'manual'}
        self.control.apply()
        self.control.set_manual('led', 35)
        self.control.apply()
        self.assertEqual(self.actuator.values['led'], 35)
        self.control.set_manual('pump', 25)
        self.actuator.allowed = False
        self.control.apply()
        self.assertEqual(self.actuator.values['pump'], 0)

    def test_light_schedule_boundaries_and_midnight(self):
        options = dict(licht_start_stunde=6, lichtdauer_stunden=16, lichtstaerke_prozent=80)
        def value(hour):
            now = datetime(2026, 5, 3, hour, tzinfo=ZoneInfo('Europe/Berlin'))
            return auto_setpoints(light_schedule(options, now))['led']
        self.assertEqual([value(h) for h in (5, 6, 21, 22)], [0, 80, 80, 0])
        options['licht_start_stunde'] = 18
        self.assertEqual([value(h) for h in (17, 18, 9, 10)], [0, 80, 80, 0])
