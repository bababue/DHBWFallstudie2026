"""LED-Stripe an GPIO12 mit konstanter Helligkeit betreiben."""

import signal
import time

from gpiozero import PWMLED
from gpiozero.pins.lgpio import LGPIOFactory


GPIO = 12
stoppen = False


def beenden(_signal, _frame):
    global stoppen
    stoppen = True


def main():
    signal.signal(signal.SIGTERM, beenden)
    led = PWMLED(GPIO, frequency=800, initial_value=0.5, pin_factory=LGPIOFactory(chip=0))

    try:
        while not stoppen:
            time.sleep(1)
    finally:
        led.close()


if __name__ == "__main__":
    main()
