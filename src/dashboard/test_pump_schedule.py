import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from pump_control import PumpRegulator
from pump_schedule import PumpSchedule
from test_pump_control import OPTIONS, state

OPTIONS = dict(OPTIONS, pumpe_start_stunde=6, pumpe_start_minute=0)
BERLIN = ZoneInfo('Europe/Berlin')

def at(day, hour, minute):
    return datetime(2026, 5, day, hour, minute, tzinfo=BERLIN)

class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'state.json'
        self.schedule = PumpSchedule(self.path)
        self.pump = PumpRegulator()

    def update(self, data, day=3, hour=6, minute=0):
        return self.schedule.update(data, OPTIONS, self.pump, at(day, hour, minute))

    def test_one_cycle_per_day_survives_restart(self):
        self.assertEqual(self.update(state(), hour=5, minute=59), 0)
        self.assertEqual(self.update(state()), 25)
        self.assertEqual(self.update(state(level=1.3)), 0)
        self.assertFalse(self.schedule.active)
        self.assertEqual(self.update(state()), 0)
        self.schedule = PumpSchedule(self.path)
        self.assertEqual(self.update(state()), 0)
        self.assertEqual(self.update(state(), day=4), 25)

    def test_next_run_before_after_and_completed_slot(self):
        self.assertEqual(self.schedule.next_run(OPTIONS, at(3, 5, 0)), at(3, 6, 0).isoformat())
        self.assertEqual(self.schedule.next_run(OPTIONS, at(3, 6, 1)), at(4, 6, 0).isoformat())
        self.schedule.mark_today('2026-05-03')
        self.assertEqual(self.schedule.next_run(OPTIONS, at(3, 6, 0)), at(4, 6, 0).isoformat())
        self.schedule.last_day = 'unknown'
        self.assertIsNone(self.schedule.next_run(OPTIONS, at(3, 6, 0)))

    def test_missed_time_does_not_run_late(self):
        self.assertEqual(self.update(state(), hour=6, minute=1), 0)
        self.assertFalse(self.path.exists())

    def test_missing_data_skips_schedule_and_stops_active(self):
        self.assertEqual(self.update(None), 0)
        self.assertEqual(self.update(state()), 0)
        self.schedule.request(True, state())
        self.assertEqual(self.update(None, minute=1), 0)
        self.assertFalse(self.schedule.active)
        with self.assertRaises(ValueError):
            self.schedule.request(True, None)

    def test_manual_cycle_and_cancel(self):
        self.schedule.request(True, state())
        self.assertEqual(self.update(state(), hour=12), 25)
        self.schedule.request(False, None)
        self.assertEqual(self.update(state(), hour=12), 0)
        self.schedule.request(True, state(level=1.3))
        self.assertEqual(self.update(state(level=1.3), hour=12), 0)
        self.assertFalse(self.schedule.active)

    def test_cannot_run_schedule_if_state_cannot_be_saved(self):
        self.schedule = PumpSchedule(self.path / 'missing' / 'state.json')
        self.assertEqual(self.update(state()), 0)
        self.assertFalse(self.schedule.active)

    def test_corrupt_state_fails_closed(self):
        self.path.write_text('invalid')
        self.schedule = PumpSchedule(self.path)
        self.assertEqual(self.update(state()), 0)
