"""Write sensor points without blocking the hardware sampling loop."""

import logging
from collections import deque
from threading import Condition, Thread


LOG = logging.getLogger("moos.storage")


class BufferedWriter:
    def __init__(self, write, stop, max_points=2000):
        self.write = write
        self.stop = stop
        self.max_points = max_points
        self.pending = deque()
        self.condition = Condition()
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, points):
        if not points:
            return
        with self.condition:
            self.pending.extend(points)
            self._trim()
            self.condition.notify()

    def _trim(self):
        overflow = len(self.pending) - self.max_points
        for _ in range(max(0, overflow)):
            self.pending.popleft()
        if overflow > 0:
            LOG.error("InfluxDB backlog exceeded %d points; %d oldest samples dropped",
                      self.max_points, overflow)

    def _run(self):
        while True:
            with self.condition:
                while not self.pending and not self.stop.is_set():
                    self.condition.wait(timeout=0.5)
                if not self.pending:
                    return
                batch = list(self.pending)
                self.pending.clear()
            try:
                self.write(batch)
            except Exception as error:
                if getattr(error, 'status', None) in (400, 422):
                    LOG.error("InfluxDB rejected batch of %d points permanently; "
                              "not retrying partial writes: %s", len(batch), error)
                    continue
                with self.condition:
                    self.pending.extendleft(reversed(batch))
                    self._trim()
                    backlog = len(self.pending)
                LOG.warning("InfluxDB write failed; retaining %d points: %s", backlog, error)
                if self.stop.wait(1.0):
                    return

    def close(self):
        with self.condition:
            self.condition.notify_all()
        self.thread.join(timeout=6)
        if self.thread.is_alive():
            LOG.error("InfluxDB writer did not stop before timeout")
