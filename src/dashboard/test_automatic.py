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

    def test_auto_pump_cannot_be_enabled_even_with_valid_measurements(self):
        self.control.apply()
        token = self.control.status()['confirmation']
        with self.assertRaisesRegex(PermissionError, 'deaktiviert'):
            self.control.set_pump_enabled(True, token)
        self.now = 100
        self.control.apply()
        self.assertFalse(self.control.enabled)
        self.assertEqual(self.actuator.values['pump'], 0)

    def test_legacy_enabled_state_is_revoked(self):
        self.control.apply()
        self.control.enabled = True
        self.actuator.values['pump'] = 25
        self.control.apply()
        self.assertFalse(self.control.enabled)
        self.assertEqual(self.actuator.values['pump'], 0)

    def test_manual_pump_cannot_be_enabled_and_other_controls_work(self):
        from actuators import PumpLocked
        self.mode = {'mode': 'MANUAL', 'session': 'manual'}
        self.control.apply()
        self.control.set_manual('led', 35)
        self.control.apply()
        self.assertEqual(self.actuator.values['led'], 35)
        with self.assertRaisesRegex(PumpLocked, 'deaktiviert'):
            self.control.set_manual('pump', 25)
        self.assertEqual(self.actuator.values['pump'], 0)

    def test_switch_off_and_failure_always_stop_pump(self):
        self.control.apply()
        self.actuator.values['pump'] = 25
        self.control.set_pump_enabled(False, None)
        self.assertEqual(self.actuator.values['pump'], 0)
        self.actuator.values['pump'] = 25
        with patch.object(self.control, 'get_water_state', side_effect=OSError('snapshot unavailable')):
            with self.assertRaises(OSError): self.control.apply()
        self.assertFalse(self.control.enabled)
        self.assertEqual(self.actuator.values['pump'], 0)

    def test_light_schedule_boundaries_and_midnight(self):
        options = dict(licht_start_stunde=6, lichtdauer_stunden=16, lichtstaerke_prozent=80)
        def value(hour):
            now = datetime(2026, 5, 3, hour, tzinfo=ZoneInfo('Europe/Berlin'))
            return auto_setpoints(light_schedule(options, now))['led']
        self.assertEqual([value(h) for h in (5, 6, 21, 22)], [0, 0, 80, 0])
        options['licht_start_stunde'] = 18
        self.assertEqual([value(h) for h in (17, 18, 9, 10)], [0, 0, 80, 0])
