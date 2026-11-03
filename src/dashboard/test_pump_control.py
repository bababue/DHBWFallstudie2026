import unittest

from pump_control import PumpRegulator, water_overview, target_level

OPTIONS = {'wasser_unter_moosspitzen_cm': 2, 'pumpe_hysterese_cm': 0.2, 'pumpe_leistung_prozent': 25}
CONFIG = {'wasserstand': {'max_fuellhoehe_cm': 8, 'sicherheitsabstand_cm': 1},
          'automatik': OPTIONS}


def state(level=0.5, target=1.3):
    return dict(water_ready=True, pump_allowed=True,
                water_level_cm=level, raw_level_cm=level, target_cm=target)


class PumpTests(unittest.TestCase):
    def test_target_tracks_moss_and_respects_safety(self):
        self.assertEqual(target_level(CONFIG, 7.5), 5.5)
        self.assertEqual(target_level(CONFIG, 1), 0)
        self.assertAlmostEqual(target_level(CONFIG, 20), 6.8)
        self.assertIsNone(water_overview([], CONFIG, 0)['target_cm'])
        self.assertEqual(PumpRegulator().value(state(target=None), OPTIONS, 0), 0)

    def test_moss_remains_displayed_and_expires(self):
        readings = [dict(side=side, sensor='ultrasonic', field='height_median_1m_cm', value=7.5, sampled=10)
                    for side in ('moss1', 'moss2')]
        self.assertEqual(water_overview(readings, CONFIG, 11)['moss_height_cm'], 7.5)
        self.assertEqual(water_overview(readings, CONFIG, 11)['target_cm'], 5.5)
        self.assertIsNone(water_overview(readings, CONFIG, 23)['target_cm'])

    def test_runs_continuously_at_25_percent_until_target(self):
        pump = PumpRegulator()
        for now in (0, 1, 6, 30, 100, 1000):
            self.assertEqual(pump.value(state(), OPTIONS, now), 25)
        self.assertEqual(pump.value(state(level=1.3), OPTIONS, 1001), 0)

    def test_initial_start_just_below_target_and_hysteresis_after_reaching(self):
        pump = PumpRegulator()
        self.assertEqual(pump.value(state(level=1.2), OPTIONS, 0), 25)
        self.assertEqual(pump.value(state(level=1.3), OPTIONS, 1), 0)
        self.assertEqual(pump.value(state(level=1.2), OPTIONS, 2), 0)
        self.assertEqual(pump.value(state(level=1.0), OPTIONS, 3), 25)

    def test_raw_high_reading_stops_even_if_filtered_water_is_lower(self):
        pump = PumpRegulator()
        pump.value(state(), OPTIONS, 0)
        data = state()
        data['raw_level_cm'] = 1.3
        self.assertEqual(pump.value(data, OPTIONS, .1), 0)

    def test_missing_water_or_safety_clearance_stops_pump(self):
        for key in ('water_ready', 'pump_allowed'):
            pump = PumpRegulator()
            pump.value(state(), OPTIONS, 0)
            data = state()
            data[key] = False
            self.assertEqual(pump.value(data, OPTIONS, .2), 0)
        self.assertEqual(PumpRegulator().value(None, OPTIONS, 0), 0)
