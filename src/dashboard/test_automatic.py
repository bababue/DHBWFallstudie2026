import unittest
from unittest.mock import MagicMock

from automatic import AutomaticControl, auto_setpoints


class AutomaticControlTests(unittest.TestCase):
    def setUp(self):
        self.mode = 'MANUAL'
        self.controller = MagicMock()
        self.controller.status.return_value = {'fan': 30, 'pump': 20, 'led': 80}
        self.automatic = AutomaticControl(self.controller, lambda: self.mode)

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

    def test_manual_values_are_only_set_in_manual(self):
        self.automatic.set_manual('fan', 30)
        self.controller.set.assert_called_once_with('fan', 30)
        self.mode = 'AUTO'
        with self.assertRaises(PermissionError):
            self.automatic.set_manual('fan', 50)

    def test_unknown_mode_does_not_apply_automatic_values(self):
        self.mode = None
        self.automatic.apply()
        self.controller.set.assert_not_called()

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
