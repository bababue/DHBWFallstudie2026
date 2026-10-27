"""LED-Stripe an GPIO12 kontinuierlich auf- und abblenden."""

import signal
import time
from itertools import chain

from gpiozero import PWMLED
from gpiozero.pins.lgpio import LGPIOFactory


GPIO = 12
SCHRITTZEIT = 0.02
stoppen = False


def beenden(_signal, _frame):
    global stoppen
    stoppen = True


def main():
    signal.signal(signal.SIGTERM, beenden)
    led = PWMLED(GPIO, frequency=800, initial_value=0, pin_factory=LGPIOFactory(chip=0))

    try:
        while not stoppen:
            for helligkeit in chain(range(101), range(99, -1, -1)):
                if stoppen:
                    break
                led.value = helligkeit / 100
                time.sleep(SCHRITTZEIT)
    finally:
        led.close()


if __name__ == "__main__":
    main()
