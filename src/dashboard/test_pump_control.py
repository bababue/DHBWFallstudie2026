import unittest

from pump_control import PumpRegulator, moss_target, target_from_height

OPTIONS = {'wasser_unter_moosspitzen_cm': 2.0, 'pumpe_hysterese_cm': 0.2,
           'pumpe_leistung_prozent': 30, 'pumpe_impuls_s': 1.0,
           'pumpe_pause_s': 5.0, 'pumpe_max_laufzeit_s': 30.0}
CONFIG = {'wasserstand': {'max_fuellhoehe_cm': 8, 'sicherheitsabstand_cm': 1},
          'automatik': OPTIONS}


def state(level=4.0, target=5.5, **kwargs):
    return dict(moss_ready=True, water_ready=True, pump_allowed=True,
                water_level_cm=level, raw_level_cm=level, target_cm=target, **kwargs)


class PumpTests(unittest.TestCase):
    def test_target_is_two_cm_below_moss_but_bounded_by_safety_limit(self):
        self.assertEqual(target_from_height(7.5, CONFIG), 5.5)
        self.assertEqual(target_from_height(1, CONFIG), 0)
        self.assertAlmostEqual(target_from_height(20, CONFIG), 6.8)
        self.assertIsNone(target_from_height(None, CONFIG))

    def test_two_stable_demo_sensors_are_allowed_but_old_or_unstable_are_not(self):
        readings = [dict(side=side, sensor='ultrasonic', field=field, value=value, sampled=10)
                    for side in ('moss1', 'moss2')
                    for field, value in [('height_median_1m_cm', 7.5), ('measurement_stable', 1), ('demo_data', True)]]
        result = moss_target(readings, CONFIG, 11)
        self.assertTrue(result['moss_ready'])
        self.assertEqual(result['target_cm'], 5.5)
        self.assertFalse(moss_target(readings, CONFIG, 23)['moss_ready'])
        readings[1]['value'] = 0
        self.assertFalse(moss_target(readings, CONFIG, 11)['moss_ready'])

    def test_pulses_pause_and_stop_at_target(self):
        pump = PumpRegulator()
        self.assertEqual(pump.value(state(), OPTIONS, 0), 30)
        self.assertEqual(pump.value(state(), OPTIONS, .9), 30)
        self.assertEqual(pump.value(state(), OPTIONS, 1), 0)
        self.assertEqual(pump.value(state(), OPTIONS, 5.9), 0)
        self.assertEqual(pump.value(state(), OPTIONS, 6), 30)
        self.assertEqual(pump.value(state(level=5.5), OPTIONS, 6.2), 0)
        self.assertFalse(pump.refilling)

    def test_hysteresis_prevents_repeated_starts_around_target(self):
        pump = PumpRegulator()
        self.assertEqual(pump.value(state(level=5.4), OPTIONS, 0), 0)
        self.assertEqual(pump.value(state(level=5.2), OPTIONS, 1), 30)

    def test_raw_high_reading_stops_even_if_filtered_water_is_lower(self):
        pump = PumpRegulator()
        pump.value(state(), OPTIONS, 0)
        data = state()
        data['raw_level_cm'] = 5.5
        self.assertEqual(pump.value(data, OPTIONS, .1), 0)

    def test_missing_water_or_moss_or_safety_clearance_stops_pump(self):
        for key in ('water_ready', 'moss_ready', 'pump_allowed'):
            pump = PumpRegulator()
            pump.value(state(), OPTIONS, 0)
            data = state()
            data[key] = False
            self.assertEqual(pump.value(data, OPTIONS, .2), 0)
        self.assertEqual(PumpRegulator().value(None, OPTIONS, 0), 0)

    def test_total_runtime_fault_latches_until_manual_reset(self):
        options = dict(OPTIONS, pumpe_max_laufzeit_s=2)
        pump = PumpRegulator()
        pump.value(state(), options, 0)
        pump.value(state(), options, 1)
        pump.value(state(), options, 6)
        self.assertEqual(pump.value(state(), options, 7), 0)
        self.assertTrue(pump.fault)
        self.assertEqual(pump.value(state(), options, 100), 0)
        pump.reset()
        self.assertEqual(pump.value(state(), options, 101), 30)
