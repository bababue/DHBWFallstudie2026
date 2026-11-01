import unittest

from actuators import Actuators


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
        self.control = Actuators(self.gpio, "/dev/gpiochip0", 20, 21, 200, 5)

    def tearDown(self):
        self.control.close()

    def test_claims_outputs_off_and_led_uses_fixed_endpoints(self):
        self.assertIn(("claim", 20, 0), self.gpio.calls)
        self.assertIn(("claim", 21, 0), self.gpio.calls)
        self.control.set("led", 30)
        self.assertIn(("pwm", 20, 200, 30), self.gpio.calls)
        self.control.set("led", 0)
        self.assertIn(("pwm", 20, 0, 0), self.gpio.calls)
        self.assertEqual(self.gpio.calls[-1], ("write", 20, 0))

    def test_fan_boost_and_low_end_scale(self):
        self.control.set("fan", 5)
        self.assertIn(("write", 21, 1), self.gpio.calls)
        self.control._finish_fan_boost(self.control.fan_generation)
        self.assertIn(("pwm", 21, 5, 25.0), self.gpio.calls)
        self.control.set("fan", 0)
        self.assertEqual(self.control.status()["fan"], 0)
        self.assertEqual(self.gpio.calls[-1], ("write", 21, 0))

    def test_rejects_invalid_commands(self):
        for device, value in (("pump", 50), ("fan", -1), ("led", 101), ("led", True)):
            with self.assertRaises(ValueError):
                self.control.set(device, value)


if __name__ == "__main__":
    unittest.main()
