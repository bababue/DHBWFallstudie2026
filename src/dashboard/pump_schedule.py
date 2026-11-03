"""One scheduled pump cycle per local day, plus an explicit immediate cycle."""
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pump_control import pump_ready


class PumpSchedule:
    def __init__(self, path=Path('/run/moos/pump-schedule.json')):
        self.path = path
        self.active = False
        self.last_day = None
        try:
            data = json.loads(path.read_text())
            self.last_day = data['last_day']
            datetime.strptime(self.last_day, '%Y-%m-%d')
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError):
            # Do not risk repeating a scheduled cycle when its state is unreadable.
            self.last_day = 'unknown'

    def next_run(self, options, now=None):
        if self.last_day == 'unknown':
            return None
        zone = ZoneInfo('Europe/Berlin')
        now = datetime.now(zone) if now is None else now.astimezone(zone)
        candidate = now.replace(hour=options['pumpe_start_stunde'], minute=options['pumpe_start_minute'], second=0, microsecond=0, fold=0)
        while (candidate < now.replace(second=0, microsecond=0)
               or candidate.date().isoformat() == self.last_day
               or datetime.fromtimestamp(candidate.timestamp(), zone).hour != candidate.hour):
            candidate += timedelta(days=1)
        return candidate.isoformat()

    def mark_today(self, day):
        if self.last_day == 'unknown':
            return False
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, delete=False) as f:
                temp = f.name
                json.dump({'last_day': day}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
        except OSError:
            try:
                os.unlink(temp)
            except (OSError, UnboundLocalError):
                pass
            return False
        self.last_day = day
        return True

    def request(self, enabled, data):
        if not enabled:
            self.active = False
            return
        if not pump_ready(data):
            raise ValueError('Keine sicheren aktuellen Messwerte')
        self.active = True

    def update(self, data, options, regulator, now=None):
        now = datetime.now(ZoneInfo('Europe/Berlin')) if now is None else now.astimezone(ZoneInfo('Europe/Berlin'))
        day = now.date().isoformat()
        if (now.hour == options['pumpe_start_stunde'] and now.minute == options['pumpe_start_minute']
                and self.last_day not in (day, 'unknown') and self.mark_today(day)):
            if pump_ready(data):
                self.active = True
                regulator.reset()
        if not self.active:
            return 0
        if not pump_ready(data):
            self.active = False
            regulator.reason = 'Pumpvorgang gestoppt: Messwerte fehlen'
            return 0
        value = regulator.value(data, options)
        if regulator.reached:
            self.active = False
        return value
