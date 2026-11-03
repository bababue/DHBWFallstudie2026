"""Automatic actuator setpoints and their application outside manual."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from configuration import load
from threading import Event, RLock, Thread

LOG = logging.getLogger('moos.automatic')


def auto_setpoints(config=None, now=None):
    """Set the LED by the local daily schedule; other outputs are currently off."""
    config = load()['automatik'] if config is None else config
    now = datetime.now(ZoneInfo('Europe/Berlin')) if now is None else now.astimezone(ZoneInfo('Europe/Berlin'))
    minute = now.hour * 60 + now.minute
    start = config['licht_start_stunde'] * 60
    duration = config['lichtdauer_stunden'] * 60
    light_on = (minute - start) % (24 * 60) < duration
    return {'fan': 0, 'pump': 0, 'led': config['lichtstaerke_prozent'] if light_on else 0}


class AutomaticControl:
    def __init__(self, actuators, get_mode):
        self.actuators = actuators
        self.get_mode = get_mode
        self.lock = RLock()
        self.stop_event = Event()
        self.thread = None

    def apply(self):
        with self.lock:
            current = self.actuators.status()
            if current['pump'] and not self.actuators.pump_allowed():
                LOG.warning('Wasserstandssperre: Pumpe wird abgeschaltet')
                self.actuators.set('pump', 0)
                current['pump'] = 0
            if self.get_mode() != 'AUTO':
                return
            for device, value in auto_setpoints().items():
                if self.get_mode() != 'AUTO':
                    return
                if current[device] != value:
                    self.actuators.set(device, value)

    def set_manual(self, device, value):
        with self.lock:
            if self.get_mode() != 'MANUAL':
                raise PermissionError('Nur im Manual-Modus verfügbar')
            return self.actuators.set(device, value)

    def start(self):
        def loop():
            while not self.stop_event.is_set():
                try:
                    self.apply()
                except Exception:
                    LOG.exception('Automatische Aktorsteuerung fehlgeschlagen')
                self.stop_event.wait(0.2)
        self.thread = Thread(target=loop, name='moos-automatic', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join()
