"""Direct distance from the ceiling-mounted sensor to the moss surface."""
import time
from measurements import DistanceFilter, MOSS_SPREAD_CM
from water_level import TimestampUltrasonic


class MossDistance(TimestampUltrasonic):
    name = "ultrasonic"

    def __init__(self, gpio, handle, trigger_pin, echo_pin):
        super().__init__(gpio, handle, trigger_pin, echo_pin, pull_down=True)
        self.filter = DistanceFilter(MOSS_SPREAD_CM)

    def read(self):
        return self.filter.update(self._distance_cm(), time.monotonic())
