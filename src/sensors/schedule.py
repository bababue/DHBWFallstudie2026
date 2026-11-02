"""Independent monotonic deadlines for sensors with different update rates."""

import math
from dataclasses import dataclass


@dataclass
class ScheduledRead:
    side: str
    sensor: object
    interval: float
    next_due: float

    def ready(self, now: float) -> bool:
        return now >= self.next_due

    def advance(self, now: float) -> None:
        """Skip missed slots instead of issuing a burst of overdue reads."""
        slots = max(1, math.floor((now - self.next_due) / self.interval) + 1)
        self.next_due += slots * self.interval
