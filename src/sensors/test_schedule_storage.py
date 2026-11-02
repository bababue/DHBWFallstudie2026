import unittest
from threading import Event

from schedule import ScheduledRead
from storage import BufferedWriter


class ScheduleTests(unittest.TestCase):
    def test_independent_deadlines_skip_missed_slots(self):
        fast = ScheduledRead("left", object(), 1.0, 10.0)
        co2 = ScheduledRead("left", object(), 0.5, 10.0)
        self.assertTrue(fast.ready(10.0))
        fast.advance(10.2)
        co2.advance(10.2)
        self.assertEqual(fast.next_due, 11.0)
        self.assertEqual(co2.next_due, 10.5)
        self.assertFalse(fast.ready(10.6))
        self.assertTrue(co2.ready(10.6))
        fast.advance(13.4)
        self.assertEqual(fast.next_due, 14.0)


class StorageTests(unittest.TestCase):
    def test_write_happens_in_background(self):
        stop = Event()
        written = Event()
        batches = []

        def write(points):
            batches.append(points)
            written.set()

        buffer = BufferedWriter(write, stop)
        buffer.submit([1, 2])
        self.assertTrue(written.wait(1))
        stop.set()
        buffer.close()
        self.assertEqual(batches, [[1, 2]])

    def test_failed_write_keeps_points_for_retry(self):
        stop = Event()
        written = Event()
        calls = []

        def write(points):
            calls.append(points)
            if len(calls) == 1:
                raise OSError("temporary outage")
            written.set()

        buffer = BufferedWriter(write, stop)
        buffer.submit([1])
        self.assertTrue(written.wait(2))
        stop.set()
        buffer.close()
        self.assertEqual(calls, [[1], [1]])


if __name__ == "__main__":
    unittest.main()
