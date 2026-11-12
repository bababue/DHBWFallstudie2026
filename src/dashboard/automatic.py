"""Automatic actuator setpoints and their application outside manual."""
import logging
import time
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from configuration import load
from pump_control import PumpRegulator
from actuators import PumpLocked
from measurements import CONTROL_INTERVAL_SECONDS
from thermal_control import ThermalRegulator
from threading import Event, RLock, Thread

LOG = logging.getLogger('moos.automatic')
MANUAL_DEFAULTS = {'pump': 0, 'led': 20, 'fan': 20}


def light_schedule(config=None, now=None):
    config = load()['automatik'] if config is None else config
    now = datetime.now(ZoneInfo('Europe/Berlin')) if now is None else now.astimezone(ZoneInfo('Europe/Berlin'))
    minute = now.hour * 60 + now.minute
    start = config['licht_start_stunde'] * 60
    duration = config['lichtdauer_stunden'] * 60
    elapsed = (minute + now.second / 60 - start) % 1440
    transition = min(config.get('licht_uebergang_minuten', 20), duration / 2)
    factor = min(1, elapsed / transition, (duration-elapsed) / transition) if transition else 1
    level = config['lichtstaerke_prozent'] * max(0, factor) if elapsed < duration else 0
    return {'start': start, 'duration': duration, 'current': minute,
            'active': (minute - start) % 1440 < duration,
            'level': level}


def auto_setpoints(schedule):
    """Set the LED by the local daily schedule; other outputs are currently off."""
    return {'fan': 0, 'pump': 0, 'led': round(schedule['level']) if schedule['active'] else 0}


class AutomaticControl:
    def __init__(self, actuators, get_mode, get_water_state=None, get_readings=None):
        self.actuators = actuators
        self.get_mode = get_mode
        self.get_water_state = get_water_state
        self.get_readings = get_readings
        self.pump = PumpRegulator()
        self.thermal = ThermalRegulator()
        self.lock = RLock()
        self.stop_event = Event()
        self.thread = None
        self.manual_initialized = False
        self.context = None
        self.mode = None
        self.enabled = False
        self.confirmation = uuid.uuid4().hex
        self.water_state = {'target_cm': None, 'water_level_cm': None, 'moss_distances_cm': {}}

    def disable_pump(self):
        with self.lock:
            self.enabled = False
            self.confirmation = uuid.uuid4().hex
            self.pump.reset()
            if self.actuators.status()['pump']:
                self.actuators.set('pump', 0)

    def status(self):
        with self.lock:
            return {**self.water_state, 'pump_enabled': self.enabled,
                    'pump_state': self.pump.state, 'reason': self.pump.reason,
                    'confirmation': self.confirmation if self.mode == 'AUTO' else None,
                    'pump_active': bool(self.actuators.status()['pump'])}

    def set_pump_enabled(self, enabled, confirmation):
        with self.lock:
            if not enabled:
                self.disable_pump()
                return self.status()
            raise PermissionError('Pumpe ist deaktiviert')

    def apply(self):
        with self.lock:
            try:
                self._apply()
            except Exception:
                self.disable_pump()
                raise

    def _apply(self):
        config = load()
        state = self.get_mode()
        self.mode = state.get('mode') if state.get('session') else None
        context = (self.mode, state.get('session'), json.dumps(config, sort_keys=True))
        if context != self.context:
            self.disable_pump()
            self.context = context
            self.thermal = ThermalRegulator()
            self.thermal.outputs.update(self.actuators.status())
        if self.get_water_state is not None:
            self.water_state = self.get_water_state(config)
        current = self.actuators.status()
        if current['pump'] and not self.actuators.pump_allowed():
            self.actuators.set('pump', 0)
            current['pump'] = 0
        if self.mode != 'MANUAL':
            self.manual_initialized = False
        if self.mode != 'AUTO':
            self.enabled = False
            self.pump.reset()
            if self.mode == 'MANUAL':
                self.initialize_manual()
            elif current['pump']:
                self.actuators.set('pump', 0)
            return
        options = config['automatik']
        schedule = light_schedule(options)
        values = auto_setpoints(schedule)
        if self.get_readings is not None:
            thermal = self.thermal.update(self.get_readings(), options, schedule, time.time())
            values.update(fan=thermal['fan'], led=thermal['led'])
        if self.enabled:
            self.disable_pump()
        self.pump.reset()
        for device, value in values.items():
            latest = self.get_mode()
            if (latest.get('mode'), latest.get('session')) != (state.get('mode'), state.get('session')):
                self.disable_pump()
                return
            if current[device] != value:
                self.actuators.set(device, value)

    def initialize_manual(self):
        if self.manual_initialized:
            return
        self.pump.reset()
        for device, value in MANUAL_DEFAULTS.items():
            if self.get_mode().get('mode') != 'MANUAL':
                return
            self.actuators.set(device, value)
        self.manual_initialized = True

    def set_manual(self, device, value):
        with self.lock:
            if self.get_mode().get('mode') != 'MANUAL':
                raise PermissionError('Nur im Manual-Modus verfügbar')
            if device == 'pump' and isinstance(value, (int, float)) and value > 0:
                raise PumpLocked('Pumpe ist deaktiviert')
            self.initialize_manual()
            return self.actuators.set(device, value)

    def start(self):
        def loop():
            while not self.stop_event.is_set():
                try:
                    self.apply()
                except Exception:
                    LOG.exception('Automatische Aktorsteuerung fehlgeschlagen')
                    try:
                        self.disable_pump()
                        self.water_state = {'target_cm': None, 'water_level_cm': None, 'moss_distances_cm': {}}
                        self.actuators.set('led', 0)
                        self.actuators.set('fan', 100)
                    except Exception:
                        LOG.exception('Sicheres Abschalten fehlgeschlagen')
                self.stop_event.wait(CONTROL_INTERVAL_SECONDS)
        self.thread = Thread(target=loop, name='moos-automatic', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join()
        self.disable_pump()
