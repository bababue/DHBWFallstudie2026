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
        self.assertEqual(PumpRegulator().value(state(target=None), OPTIONS), 0)

    def test_moss_remains_displayed_and_expires(self):
        readings = [dict(side=side, sensor='ultrasonic', field='height_median_1m_cm', value=7.5, sampled=10)
                    for side in ('moss1', 'moss2')]
        self.assertEqual(water_overview(readings, CONFIG, 11)['moss_height_cm'], 7.5)
        self.assertEqual(water_overview(readings, CONFIG, 11)['target_cm'], 5.5)
        self.assertIsNone(water_overview(readings, CONFIG, 23)['target_cm'])

    def test_runs_continuously_at_25_percent_until_target(self):
        pump = PumpRegulator()
        for _ in (0, 1, 6, 30, 100, 1000):
            self.assertEqual(pump.value(state(), OPTIONS), 25)
        self.assertEqual(pump.value(state(level=1.3), OPTIONS), 0)

    def test_initial_start_just_below_target_and_hysteresis_after_reaching(self):
        pump = PumpRegulator()
        self.assertEqual(pump.value(state(level=1.2), OPTIONS), 25)
        self.assertEqual(pump.value(state(level=1.3), OPTIONS), 0)
        self.assertEqual(pump.value(state(level=1.2), OPTIONS), 0)
        self.assertEqual(pump.value(state(level=1.0), OPTIONS), 25)

    def test_raw_high_reading_stops_even_if_filtered_water_is_lower(self):
        pump = PumpRegulator()
        pump.value(state(), OPTIONS)
        data = state()
        data['raw_level_cm'] = 1.3
        self.assertEqual(pump.value(data, OPTIONS), 0)

    def test_missing_water_or_safety_clearance_stops_pump(self):
        for key in ('water_ready', 'pump_allowed'):
            pump = PumpRegulator()
            pump.value(state(), OPTIONS)
            data = state()
            data[key] = False
            self.assertEqual(pump.value(data, OPTIONS), 0)
        self.assertEqual(PumpRegulator().value(None, OPTIONS), 0)


class StableTargetTests(unittest.TestCase):
    def setUp(self):
        from pump_control import StableWaterTarget
        self.target = StableWaterTarget()
        self.config = dict(CONFIG, moos_1={'bezugsabstand_cm': 7}, moos_2={'bezugsabstand_cm': 6})

    def update(self, now, left=7.5, right=7.5, stable=1, missing=False):
        readings = [dict(side=side, sensor='ultrasonic', field=field, value=value, sampled=now)
                    for side, height in [('moss1', left), ('moss2', right)]
                    if not (missing and side == 'moss2')
                    for field, value in [('height_median_1m_cm', height), ('measurement_stable', stable)]]
        return self.target.update(readings, self.config, now)['target_cm']

    def confirm(self, start=0, height=7.5):
        for now in range(start, start + 181, 4):
            value = self.update(now, height, height)
        return value

    def test_waits_for_three_minutes_of_real_stable_samples(self):
        for now in range(0, 180, 4):
            self.assertIsNone(self.update(now))
        self.assertEqual(self.update(180), 5.5)

    def test_jitter_does_not_move_confirmed_target(self):
        self.assertEqual(self.confirm(), 5.5)
        for now in range(184, 500, 4):
            height = 7.55 if now % 8 else 7.45
            self.assertEqual(self.update(now, height, height), 5.5)

    def test_larger_change_requires_confirmation_and_outlier_does_not_shift_target(self):
        self.confirm()
        self.assertEqual(self.update(184, 9, 9), 5.5)
        self.assertEqual(self.update(188), 5.5)
        for now in range(192, 372, 4):
            self.assertEqual(self.update(now, 8, 8), 5.5)
        self.assertEqual(self.update(372, 8, 8), 6)

    def test_missing_or_unstable_sensor_blocks_pumping_and_requires_new_confirmation(self):
        for condition in [{'missing': True}, {'stable': 0}]:
            self.target.reset()
            self.confirm()
            self.assertIsNone(self.update(184, **condition))
            self.assertIsNone(self.update(188))
            self.assertEqual(self.confirm(192), 5.5)

    def test_cached_readings_cannot_complete_confirmation(self):
        readings = [dict(side=side, sensor='ultrasonic', field=field, value=value, sampled=0)
                    for side in ['moss1', 'moss2']
                    for field, value in [('height_median_1m_cm', 7.5), ('measurement_stable', 1)]]
        self.target.update(readings, self.config, 0)
        self.assertIsNone(self.target.update(readings, self.config, 180)['target_cm'])

    def test_configuration_change_resets_confirmation(self):
        self.confirm()
        self.config['moos_2']['bezugsabstand_cm'] = None
        self.assertIsNone(self.update(184))

    def test_missing_moss_target_stops_a_running_pump(self):
        pump = PumpRegulator()
        self.assertEqual(pump.value(state(), OPTIONS), 25)
        self.assertEqual(pump.value(state(target=None), OPTIONS), 0)
