"""Software I2C and drivers for the six installed I2C sensors.

The handover reports nonstandard GPIO pairs and an electrical issue with
open-drain high levels. This bus actively drives its own high bits, while
releasing SDA for sensor responses. Use only after the 3.3 V wiring is checked.
"""

import time


def crc8(data: bytes) -> int:
    """Sensirion CRC-8: polynomial 0x31, initial value 0xff."""
    crc = 0xFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def checked_word(data: bytes) -> int:
    if len(data) != 3 or crc8(data[:2]) != data[2]:
        raise ValueError("Sensor CRC error")
    return int.from_bytes(data[:2], "big")


class SoftwareI2C:
    def __init__(self, lgpio, handle: int, sda: int, scl: int, delay_us: int):
        self.gpio = lgpio
        self.handle = handle
        self.sda = sda
        self.scl = scl
        self.delay = delay_us / 1_000_000
        self.gpio.gpio_claim_output(handle, scl, 1)
        self.gpio.gpio_claim_output(handle, sda, 1)
        self.sda_is_output = True

    def _pause(self):
        time.sleep(self.delay)

    def _sda(self, level: int):
        if self.sda_is_output:
            self.gpio.gpio_write(self.handle, self.sda, level)
        else:
            self.gpio.gpio_claim_output(self.handle, self.sda, level)
            self.sda_is_output = True

    def _sda_input(self):
        if self.sda_is_output:
            self.gpio.gpio_claim_input(self.handle, self.sda)
            self.sda_is_output = False

    def _scl(self, level: int):
        self.gpio.gpio_write(self.handle, self.scl, level)

    def _start(self):
        self._sda_input()
        self._scl(1)
        # A broken transaction may leave a sensor holding SDA low.
        for _ in range(9):
            if self.gpio.gpio_read(self.handle, self.sda):
                break
            self._scl(0)
            self._pause()
            self._scl(1)
            self._pause()
        else:
            raise OSError("I2C SDA remains low after bus recovery")
        self._sda(1)
        self._pause()
        self._sda(0)
        self._pause()
        self._scl(0)

    def _stop(self):
        self._sda(0)
        self._pause()
        self._scl(1)
        self._pause()
        self._sda(1)
        self._pause()

    def _write_byte(self, value: int):
        for bit in range(7, -1, -1):
            self._sda((value >> bit) & 1)
            self._pause()
            self._scl(1)
            self._pause()
            self._scl(0)
        self._sda_input()
        self._pause()
        self._scl(1)
        self._pause()
        acknowledged = self.gpio.gpio_read(self.handle, self.sda) == 0
        self._scl(0)
        self._sda(1)
        if not acknowledged:
            raise OSError(f"I2C NACK for byte 0x{value:02x}")

    def _read_byte(self, acknowledge: bool) -> int:
        self._sda_input()
        value = 0
        for _ in range(8):
            self._pause()
            self._scl(1)
            self._pause()
            value = (value << 1) | self.gpio.gpio_read(self.handle, self.sda)
            self._scl(0)
        self._sda(0 if acknowledge else 1)
        self._pause()
        self._scl(1)
        self._pause()
        self._scl(0)
        self._sda(1)
        return value

    def write(self, address: int, payload: bytes):
        self._start()
        try:
            self._write_byte(address << 1)
            for value in payload:
                self._write_byte(value)
        finally:
            self._stop()

    def read(self, address: int, count: int) -> bytes:
        self._start()
        try:
            self._write_byte((address << 1) | 1)
            return bytes(self._read_byte(i < count - 1) for i in range(count))
        finally:
            self._stop()

    def close(self):
        self._sda_input()
        self.gpio.gpio_claim_input(self.handle, self.scl)
        self.gpio.gpio_free(self.handle, self.sda)
        self.gpio.gpio_free(self.handle, self.scl)


class SHT45:
    name = "sht45"

    def __init__(self, bus: SoftwareI2C, address: int):
        self.bus = bus
        self.address = address

    def read(self) -> dict[str, float]:
        self.bus.write(self.address, b"\xfd")
        time.sleep(0.02)
        data = self.bus.read(self.address, 6)
        temperature = -45 + 175 * checked_word(data[:3]) / 65535
        humidity = -6 + 125 * checked_word(data[3:]) / 65535
        return {"temperature_c": temperature, "humidity_pct": min(100.0, max(0.0, humidity))}


class BH1750:
    name = "bh1750"

    def __init__(self, bus: SoftwareI2C, address: int):
        self.bus = bus
        self.address = address

    def read(self) -> dict[str, float]:
        # One-time high-resolution measurement, then automatic power-down.
        self.bus.write(self.address, b"\x01")
        self.bus.write(self.address, b"\x20")
        time.sleep(0.18)
        raw = int.from_bytes(self.bus.read(self.address, 2), "big")
        return {"illuminance_lux": raw / 1.2}


class SCD40:
    name = "scd40"

    def __init__(self, bus: SoftwareI2C, address: int):
        self.bus = bus
        self.address = address

    def _command(self, command: int):
        self.bus.write(self.address, command.to_bytes(2, "big"))

    def start(self):
        # A prior process may have left periodic measurement active.
        self._command(0x3F86)
        time.sleep(0.5)
        self._command(0x21B1)

    def read(self) -> dict[str, float] | None:
        self._command(0xE4B8)
        time.sleep(0.002)
        status = checked_word(self.bus.read(self.address, 3))
        if status & 0x07FF == 0:
            return None
        self._command(0xEC05)
        time.sleep(0.002)
        data = self.bus.read(self.address, 9)
        return {
            "co2_ppm": float(checked_word(data[:3])),
            "temperature_c": -45 + 175 * checked_word(data[3:6]) / 65535,
            "humidity_pct": 100 * checked_word(data[6:]) / 65535,
        }

    def stop(self):
        self._command(0x3F86)
