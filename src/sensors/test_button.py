import json
import tempfile
import unittest
from pathlib import Path

from button import ButtonModes, MODES, apply_mode_command


class ButtonModesTests(unittest.TestCase):
    def test_short_press_cycles_modes_only_after_release(self):
        modes = ButtonModes()
        self.assertEqual(MODES, ("AUTO", "MANUAL"))
        self.assertEqual(modes.snapshot()[:2], ("AUTO", False))
        for index in range(1, len(MODES) + 1):
            start = index * 2.0
            modes.feed(True, start)
            modes.feed(True, start + 0.05)
            self.assertEqual(modes.snapshot()[0], MODES[index - 1])
            modes.feed(False, start + 0.15)
            modes.feed(False, start + 0.20)
            self.assertEqual(modes.snapshot()[:2], (MODES[index % len(MODES)], False))

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

    def test_hold_shows_info_without_changing_mode(self):
        modes = ButtonModes()
        modes.feed(True, 1.0)
        modes.feed(True, 1.05)
        modes.feed(True, 1.66)
        self.assertEqual(modes.snapshot()[:2], ("AUTO", True))
        modes.feed(False, 1.7)
        modes.feed(False, 1.75)
        self.assertEqual(modes.snapshot()[:2], ("AUTO", False))

    def test_bounce_does_not_switch_mode(self):
        modes = ButtonModes()
        modes.feed(True, 1.0)
        modes.feed(False, 1.02)
        modes.feed(False, 1.10)
        self.assertEqual(modes.snapshot()[:2], ("AUTO", False))


if __name__ == "__main__":
    unittest.main()
