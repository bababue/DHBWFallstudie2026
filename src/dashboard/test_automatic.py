import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, patch

from automatic import AutomaticControl, auto_setpoints, light_schedule


class AutomaticControlTests(unittest.TestCase):
    def setUp(self):
        self.mode = 'MANUAL'
        self.controller = MagicMock()
        self.controller.status.return_value = {'fan': 30, 'pump': 20, 'led': 80}
        self.automatic = AutomaticControl(self.controller, lambda: self.mode)
        self.schedule = patch('automatic.auto_setpoints', return_value={'fan': 0, 'pump': 0, 'led': 0})
        self.schedule.start()
        self.addCleanup(self.schedule.stop)

    def test_light_schedule_boundaries_and_midnight(self):
        self.schedule.stop()
        berlin = ZoneInfo('Europe/Berlin')
        config = {'licht_start_stunde': 6, 'lichtdauer_stunden': 16, 'lichtstaerke_prozent': 80}
        def value(hour, minute):
            return auto_setpoints(config, datetime(2026, 5, 3, hour, minute, tzinfo=berlin))['led']
        self.assertEqual([value(5, 59), value(6, 0), value(21, 59), value(22, 0)], [0, 80, 80, 0])
        night = light_schedule(config, datetime(2026, 5, 3, 22, 0, tzinfo=berlin))
        self.assertFalse(night['active'])
        self.assertEqual((night['start'], night['duration'], night['current']), (360, 960, 1320))
        config['licht_start_stunde'] = 18
        self.assertEqual([value(17, 59), value(18, 0), value(9, 59), value(10, 0)], [0, 80, 80, 0])

    def test_water_lock_stops_running_pump_even_in_manual_or_unknown_mode(self):
        self.controller.pump_allowed.return_value = False
        self.automatic.apply()
        self.controller.set.assert_called_once_with('pump', 0)
        self.controller.set.reset_mock()
        self.controller.status.return_value['pump'] = 20
        self.mode = None
        self.automatic.apply()
        self.controller.set.assert_called_once_with('pump', 0)

    def test_auto_restores_all_setpoints_after_manual(self):
        self.automatic.apply()
        self.controller.set.assert_not_called()
        self.mode = 'AUTO'
        self.automatic.apply()
        self.assertEqual(auto_setpoints(), {'fan': 0, 'pump': 0, 'led': 0})
        self.assertEqual(self.controller.set.call_count, 3)
        for device in ('fan', 'pump', 'led'):
            self.controller.set.assert_any_call(device, 0)

    def test_auto_drives_pump_from_regulator_and_manual_keeps_control(self):
        from test_pump_control import OPTIONS, state
        self.automatic.get_water_state = lambda: (state(), OPTIONS)
        self.mode = 'AUTO'
        self.controller.status.return_value = {'fan': 0, 'pump': 0, 'led': 0}
        self.automatic.apply()
        self.controller.set.assert_called_once_with('pump', 30)
        self.controller.set.reset_mock()
        self.mode = 'MANUAL'
        self.automatic.apply()
        self.controller.set.assert_not_called()
        self.assertIsNone(self.automatic.pump.pulse_started)

    def test_manual_values_are_only_set_in_manual(self):
        self.automatic.set_manual('fan', 30)
        self.controller.set.assert_called_once_with('fan', 30)
        self.mode = 'AUTO'
        with self.assertRaises(PermissionError):
            self.automatic.set_manual('fan', 50)

    def test_unknown_mode_stops_pump_without_applying_other_values(self):
        self.mode = None
        self.automatic.apply()
        self.controller.set.assert_called_once_with('pump', 0)

    def test_auto_does_not_repeat_unchanged_outputs(self):
        self.mode = 'AUTO'
        self.controller.status.return_value = auto_setpoints()
        self.automatic.apply()
        self.controller.set.assert_not_called()

    def test_auto_stops_if_mode_changes_during_update(self):
        modes = iter(['AUTO', 'AUTO', 'MANUAL'])
        self.automatic.get_mode = lambda: next(modes)
        self.automatic.apply()
        self.assertEqual(self.controller.set.call_count, 1)


if __name__ == '__main__':
    unittest.main()
