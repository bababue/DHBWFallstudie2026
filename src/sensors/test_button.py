import unittest

from button import ButtonModes, MODES


class ButtonModesTests(unittest.TestCase):
    def test_short_press_cycles_modes_only_after_release(self):
        modes = ButtonModes()
        self.assertEqual(modes.snapshot()[:2], ("AUTO", False))
        for index in range(1, len(MODES) + 1):
            start = index * 2.0
            modes.feed(True, start)
            modes.feed(True, start + 0.05)
            self.assertEqual(modes.snapshot()[0], MODES[index - 1])
            modes.feed(False, start + 0.15)
            modes.feed(False, start + 0.20)
            self.assertEqual(modes.snapshot()[:2], (MODES[index % len(MODES)], False))

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
