import unittest
from unittest.mock import patch

from actuators import Actuators, PumpLocked


class FakeGpio:
    TX_PWM = 1

    def __init__(self):
        self.calls = []
        self.busy = set()

    def gpiochip_open(self, chip):
        self.calls.append(("open", chip))
        return 7

    def gpio_claim_output(self, handle, pin, level):
        self.calls.append(("claim", pin, level))

    def tx_busy(self, handle, pin, kind):
        return pin in self.busy

    def tx_pwm(self, handle, pin, hz, duty):
        self.calls.append(("pwm", pin, hz, duty))
        if hz == 0:
            self.busy.discard(pin)
        else:
            self.busy.add(pin)

    def gpio_write(self, handle, pin, level):
        self.calls.append(("write", pin, level))

    def gpiochip_close(self, handle):
        self.calls.append(("close", handle))


class ActuatorTests(unittest.TestCase):
    def setUp(self):
        self.gpio = FakeGpio()
        self.control = Actuators(self.gpio, "/dev/gpiochip0", 20, 21, 16, 200, 5, 5, pump_allowed=lambda: True)

    def tearDown(self):
        self.control.close()

    def test_claims_outputs_off_and_led_uses_fixed_endpoints(self):
        self.assertIn(("claim", 20, 0), self.gpio.calls)
        self.assertIn(("claim", 21, 0), self.gpio.calls)
        self.assertIn(("claim", 16, 0), self.gpio.calls)
        self.control.set("led", 5)
        self.assertIn(("pwm", 20, 200, 5), self.gpio.calls)
        self.control.set("led", 0)
        self.assertIn(("pwm", 20, 0, 0), self.gpio.calls)
        self.assertEqual(self.gpio.calls[-1], ("write", 20, 0))

    def test_fan_boost_and_low_end_scale(self):
        with patch("actuators.threading.Timer") as timer:
            self.control.set("fan", 5)
        self.assertEqual(timer.call_args.args[0], 0.5)
        self.assertIn(("write", 21, 1), self.gpio.calls)
        self.control._finish_boost("fan", self.control.generations["fan"])
        self.assertIn(("pwm", 21, 5, 25.0), self.gpio.calls)
        self.control.set("fan", 0)
        self.assertEqual(self.control.status()["fan"], 0)
        self.assertEqual(self.gpio.calls[-1], ("write", 21, 0))

    def test_pump_is_disabled_even_if_the_water_interlock_allows_it(self):
        for value in (5, 25, 100):
            with self.assertRaisesRegex(PumpLocked, 'deaktiviert'):
                self.control.set('pump', value)
        self.assertFalse(any(call[0] == 'pwm' and call[1] == 16 and call[2] for call in self.gpio.calls))
        self.assertEqual(self.control.status()['pump'], 0)
        self.control.set('pump', 0)

    def test_updates_during_boost_keep_original_timer_and_use_latest_target(self):
        with patch('actuators.threading.Timer') as timer:
            self.control.set('fan', 5)
            generation = self.control.generations['fan']
            calls = list(self.gpio.calls)
            for target in (6, 12, 65):
                self.control.set('fan', target)
            timer.assert_called_once()
            timer.return_value.cancel.assert_not_called()
            self.assertEqual(self.gpio.calls, calls)
            self.assertEqual(self.control.generations['fan'], generation)
            self.assertEqual(self.control.status()['fan'], 65)
            self.control._finish_boost('fan', generation)
            self.assertEqual(self.gpio.calls[-1], ('pwm', 21, 5, self.control.duty('fan', 65)))

    def test_old_boost_callback_cannot_finish_new_start(self):
        with patch('actuators.threading.Timer'):
            self.control.set('fan', 5)
            old_generation = self.control.generations['fan']
            self.control.set('fan', 0)
            self.assertEqual(self.gpio.calls[-1], ('write', 21, 0))
            self.control.set('fan', 10)
            calls = list(self.gpio.calls)
            self.control._finish_boost('fan', old_generation)
            self.assertEqual(self.gpio.calls, calls)
            self.control._finish_boost('fan', self.control.generations['fan'])
            self.assertEqual(self.gpio.calls[-1], ('pwm', 21, 5, self.control.duty('fan', 10)))

    def test_led_supports_one_percent_ramp_resolution(self):
        for value in (1, 2, 3, 4):
            self.control.set('led', value)
            self.assertEqual(self.gpio.calls[-1], ('pwm', 20, 200, value))

    def test_stop_during_boost_keeps_both_motors_off(self):
        with patch("actuators.threading.Timer"):
            self.control.set("fan", 50)
        generations = dict(self.control.generations)
        self.control.set("fan", 0)
        self.control.set("pump", 0)
        self.control._finish_boost("fan", generations["fan"])
        self.assertEqual(self.control.status(), {"led": 0, "fan": 0, "pump": 0})
        self.assertEqual(self.gpio.calls[-1], ("write", 16, 0))

    def test_scale_is_linear_and_boost_only_applies_in_start_range(self):
        with patch("actuators.threading.Timer") as timer:
            self.control.set("fan", 55)
        timer.assert_not_called()
        self.assertAlmostEqual(self.control.duty("fan", 55), 25 + 50 * 75 / 95)
        self.assertAlmostEqual(self.control.duty("pump", 35), 35)
        self.control.set("led", 100)
        self.assertIn(("write", 20, 1), self.gpio.calls)
        self.control.set("fan", 100)
        self.assertIn(("write", 21, 1), self.gpio.calls)

    def test_pump_cannot_start_when_interlock_is_closed(self):
        self.control.pump_allowed = lambda: False
        with self.assertRaises(PumpLocked):
            self.control.set('pump', 50)
        self.assertEqual(self.control.status()['pump'], 0)
        self.control.set('pump', 0)

    def test_rejects_invalid_commands(self):
        for device, value in (("other", 50), ("fan", -1), ("led", 101), ("led", True), ("pump", 1)):
            with self.assertRaises(ValueError):
                self.control.set(device, value)


if __name__ == "__main__":
    unittest.main()
