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
        return self.reg.update(readings(temp), OPTIONS, dict(active=active, level=50), now)

    def test_continuous_outputs_slew_and_immediate_cutoff(self):
        options = dict(OPTIONS, temperatur_glaettung_s=0, stellwert_aenderung_prozent_pro_s=2)
        def update(temp, now, active=True):
            data = [dict(r, sampled=now) for r in readings(temp)]
            return self.reg.update(data, options, dict(active=active, level=100), now)
        self.assertEqual(update(20.5, 100)['led'], 0)
        self.assertEqual(update(20.5, 110)['led'], 20)
        self.assertEqual(update(20.5, 150)['led'], 100)
        result = update(23, 170)
        self.assertEqual(result['fan'], 33)
        self.assertEqual(result['led'], 67)
        result = update(25, 170.1)
        self.assertEqual((result['fan'], result['led']), (100, 0))
        self.assertEqual(update(24, 180)['led'], 0)
        self.assertGreater(update(23.9, 190)['led'], 0)
        self.assertEqual(update(23, 250, False)['fan'], 0)

    def test_smoothing_cannot_delay_raw_overheat(self):
        self.value(20)
        data = [dict(r, sampled=101) for r in readings(25)]
        result = self.reg.update(data, OPTIONS, dict(active=True, level=100), 101)
        self.assertEqual((result['fan'], result['led']), (100, 0))

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

class IntegrationTests(unittest.TestCase):
    def test_auto_controls_actual_outputs_and_manual_is_untouched(self):
        from automatic import AutomaticControl
        from unittest.mock import MagicMock, patch
        actuator = MagicMock()
        actuator.status.return_value = dict(fan=0, pump=0, led=100)
        control = AutomaticControl(actuator, lambda: {'mode': 'AUTO', 'session': 'one'}, get_readings=lambda: readings(25))
        with patch('automatic.time.time', return_value=100), patch('automatic.load', return_value={'automatik': OPTIONS}), patch('automatic.light_schedule', return_value=dict(active=True, level=100)), patch('automatic.auto_setpoints', return_value=dict(fan=0, pump=0, led=100)):
            control.apply()
            actuator.set.assert_any_call('fan', 100)
            actuator.set.assert_any_call('led', 0)
            actuator.set.reset_mock()
            control.get_mode = lambda: {'mode': 'MANUAL', 'session': 'two'}
            control.apply()
            actuator.set.assert_any_call('pump', 0)
            actuator.set.assert_any_call('led', 20)
            actuator.set.assert_any_call('fan', 20)
