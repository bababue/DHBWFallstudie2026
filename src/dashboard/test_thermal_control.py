import unittest
from thermal_control import ThermalRegulator, temperatures

OPTIONS = {'temperatur_ziel_c': 22, 'temperatur_max_c': 25}

def readings(left, right=None):
    return [dict(side=side, sensor='sht45', field='temperature_c', value=value, sampled=100)
            for side, value in [('left', left), ('right', left if right is None else right)]]

class ThermalTests(unittest.TestCase):
    def setUp(self):
        self.reg = ThermalRegulator()

    def value(self, temp, active=True, now=100):
        return self.reg.update(readings(temp), OPTIONS, dict(active=active, level=100), now)

    def test_daytime_cooling_and_dimming(self):
        self.assertEqual((self.value(21)['fan'], self.value(21)['led']), (0, 100))
        self.assertGreater(self.value(22.5)['fan'], 0)
        self.assertEqual(self.value(22.5)['led'], 100)
        self.assertEqual(self.value(24)['led'], 50)
        self.assertGreater(self.value(24)['fan'], self.value(23)['fan'])

    def test_cutoff_and_recovery_hysteresis(self):
        self.assertEqual(self.value(25)['led'], 0)
        self.assertEqual(self.value(24.5)['fan'], 100)
        self.assertEqual(self.value(24)['led'], 0)
        self.assertGreater(self.value(23.9)['led'], 0)

    def test_night_stays_dark_but_overheat_protected(self):
        self.assertEqual(self.value(23, False)['fan'], 0)
        self.assertEqual(self.value(23, False)['led'], 0)
        self.assertEqual(self.value(25, False)['fan'], 100)
        self.assertEqual(self.value(23, False)['fan'], 0)

    def test_stale_or_missing_sides_fail_safe(self):
        self.assertEqual(self.value(22, now=113)['led'], 0)
        state = self.reg.update(readings(22)[:1], OPTIONS, dict(active=True, level=100), 100)
        self.assertEqual((state['led'], state['fan']), (0, 100))

    def test_fallback_and_hotter_side(self):
        data = readings(21, 25)
        data += [dict(data[0], sensor='scd40', value=30)]
        self.assertEqual(temperatures(data, 100), [21, 25])
        self.assertEqual(temperatures(data[1:], 100), [30, 25])
        self.assertEqual(self.reg.update(data, OPTIONS, dict(active=True, level=100), 100)['led'], 0)

    def test_fan_deadband(self):
        self.assertEqual(self.value(22.2)['fan'], 0)
        self.assertGreater(self.value(22.4)['fan'], 0)
        self.assertGreater(self.value(22.1)['fan'], 0)
        self.assertEqual(self.value(22)['fan'], 0)

class IntegrationTests(unittest.TestCase):
    def test_auto_controls_actual_outputs_and_manual_is_untouched(self):
        from automatic import AutomaticControl
        from unittest.mock import MagicMock, patch
        actuator = MagicMock()
        actuator.status.return_value = dict(fan=0, pump=0, led=100)
        control = AutomaticControl(actuator, lambda: 'AUTO', get_readings=lambda: readings(25))
        with patch('automatic.time.time', return_value=100), patch('automatic.load', return_value={'automatik': OPTIONS}), patch('automatic.light_schedule', return_value=dict(active=True, level=100)), patch('automatic.auto_setpoints', return_value=dict(fan=0, pump=0, led=100)):
            control.apply()
            actuator.set.assert_any_call('fan', 100)
            actuator.set.assert_any_call('led', 0)
            actuator.set.reset_mock()
            control.get_mode = lambda: 'MANUAL'
            control.apply()
            actuator.set.assert_not_called()
