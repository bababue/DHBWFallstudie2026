import unittest

from display import ButtonMenu
from oled import BREITE, HOEHE, render


class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.values = {"led": 0, "pump": 0, "fan": 0}
        self.commands = []

        def set_value(device, value):
            self.commands.append((device, value))
            self.values[device] = value

        self.menu = ButtonMenu(set_value)
        self.now = 10.0

    def tick(self, pressed, seconds=0.02):
        self.now += seconds
        return self.menu.tick(pressed, self.now, self.values)

    def click(self):
        self.tick(True)
        self.tick(False, 0.1)

    def double_click(self):
        self.click()
        self.tick(True, 0.1)
        self.tick(False, 0.1)

    def test_double_click_cycles_four_views_without_changing_values(self):
        for expected in (1, 2, 3, 0):
            self.double_click()
            self.assertEqual(self.menu.view, expected)
            self.tick(False, 0.5)
        self.assertEqual(self.commands, [])

    def test_single_click_increases_only_current_control(self):
        self.double_click()  # Licht
        self.tick(False, 0.5)
        self.click()
        self.assertEqual(self.commands, [])  # Wait for double-click window.
        self.tick(False, 0.5)
        self.assertEqual(self.commands, [("led", 5)])
        self.values["led"] = 100
        self.click()
        self.tick(False, 0.5)
        self.assertEqual(self.values["led"], 100)

    def test_long_press_resets_current_control_once(self):
        self.double_click()  # Licht
        self.tick(False, 0.5)
        self.values["led"] = 70
        self.tick(True)
        self.tick(True, 1.01)
        self.tick(True, 1.0)
        self.tick(False)
        self.tick(False, 0.5)
        self.assertEqual(self.commands, [("led", 0)])

    def test_sensor_click_and_long_press_do_not_change_controls(self):
        self.click()
        self.tick(False, 0.5)
        self.tick(True)
        self.tick(True, 1.5)
        self.tick(False)
        self.assertEqual(self.menu.view, 0)
        self.assertEqual(self.commands, [])


class OledTests(unittest.TestCase):
    def test_all_views_fit_display_buffer(self):
        readings = {("left", "sht45", "temperature_c"): 21.5,
                    ("right", "scd40", "co2_ppm"): 530}
        controls = {"led": 25, "pump": 50, "fan": 75}
        for view in range(4):
            self.assertEqual(len(render(view, readings, controls, True)), BREITE * HOEHE // 8)


if __name__ == "__main__":
    unittest.main()
