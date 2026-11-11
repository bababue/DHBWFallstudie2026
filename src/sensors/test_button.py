import json
import tempfile
import unittest
from pathlib import Path

from button import ButtonModes, MODES, apply_mode_command


class ButtonModesTests(unittest.TestCase):
    def test_restart_and_every_actual_mode_transition_have_new_sessions(self):
        modes = ButtonModes()
        initial = modes.control_state()
        self.assertNotEqual(initial['session'], ButtonModes().control_state()['session'])
        modes.set_mode('MANUAL')
        manual = modes.control_state()
        modes.set_mode('AUTO')
        auto = modes.control_state()
        self.assertEqual(auto['mode'], 'AUTO')
        self.assertEqual(len({initial['session'], manual['session'], auto['session']}), 3)
        modes.set_mode('AUTO')
        self.assertEqual(auto, modes.control_state())

    def test_press_switches_mode_once_and_release_does_not_switch(self):
        modes = ButtonModes()
        self.assertEqual(MODES, ("AUTO", "MANUAL"))
        self.assertEqual(modes.snapshot()[0], "AUTO")
        for index in range(1, len(MODES) + 1):
            start = index * 2.0
            modes.feed(True, start)
            modes.feed(True, start + 0.05)
            self.assertEqual(modes.snapshot()[0], MODES[index % len(MODES)])
            modes.feed(False, start + 0.15)
            modes.feed(False, start + 0.20)
            self.assertEqual(modes.snapshot()[0], MODES[index % len(MODES)])

    def test_web_commands_are_fresh_and_applied_only_once(self):
        modes = ButtonModes()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mode-command.json'
            path.write_text(json.dumps({'id': 'one', 'mode': 'MANUAL', 'requested': 10}))
            self.assertEqual(apply_mode_command(modes, path, None, 11), 'one')
            self.assertEqual(modes.snapshot()[0], 'MANUAL')
            modes.set_mode('AUTO')
            self.assertEqual(apply_mode_command(modes, path, 'one', 12), 'one')
            self.assertEqual(modes.snapshot()[0], 'AUTO')
            path.write_text(json.dumps({'id': 'two', 'mode': 'MANUAL', 'requested': 10}))
            self.assertEqual(apply_mode_command(modes, path, 'one', 16), 'one')
            self.assertEqual(modes.snapshot()[0], 'AUTO')
            path.write_text(json.dumps({'id': 'three', 'mode': 'AUTO', 'requested': 16}))
            self.assertEqual(apply_mode_command(modes, path, 'one', 16), 'three')

    def test_hold_switches_once_and_keeps_mode(self):
        modes = ButtonModes()
        modes.feed(True, 1.0)
        modes.feed(True, 1.05)
        modes.feed(True, 1.66)
        self.assertEqual(modes.snapshot()[0], "MANUAL")
        modes.feed(False, 1.7)
        modes.feed(False, 1.75)
        self.assertEqual(modes.snapshot()[0], "MANUAL")

    def test_manual_expires_from_button_or_web_without_refreshing_on_same_mode(self):
        modes = ButtonModes(manual_timeout_seconds=3600)
        modes.feed(True, 10)
        modes.feed(True, 10.05)
        manual = modes.control_state()
        modes.expire(3610.04)
        self.assertEqual(modes.control_state(), manual)
        modes.set_mode('MANUAL', now=100)
        modes.expire(3610.05)
        self.assertEqual(modes.snapshot()[0], 'AUTO')
        self.assertNotEqual(modes.control_state()['session'], manual['session'])
        modes.set_mode('MANUAL', now=5000)
        modes.expire(8599.9)
        self.assertEqual(modes.snapshot()[0], 'MANUAL')
        modes.expire(8600)
        self.assertEqual(modes.snapshot()[0], 'AUTO')

    def test_bounce_does_not_switch_mode(self):
        modes = ButtonModes()
        modes.feed(True, 1.0)
        modes.feed(False, 1.02)
        modes.feed(False, 1.10)
        self.assertEqual(modes.snapshot()[0], "AUTO")


if __name__ == "__main__":
    unittest.main()
