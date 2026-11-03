import copy
import unittest
from pump_control import PumpRegulator, water_overview, pump_ready

OPTIONS = {'wasser_unter_moosspitzen_cm': 2.5, 'pumpe_hysterese_cm': .2, 'pumpe_leistung_prozent': 25}
CONFIG = {'wasserstand': {'max_fuellhoehe_cm': 7}, 'automatik': OPTIONS,
          'moos': {'montagehoehe_cm': 13.1, 'sensoren': {f'moos_{i}': {} for i in range(1, 5)}}}


def state(level=3, target=5):
    return dict(water_ready=True, pump_allowed=True, water_level_cm=level, target_cm=target)


def readings(now=10):
    return [dict(side=side, sensor='ultrasonic', field=field, value=value, sampled=now)
            for side, distance in [('moss1', 5.6), ('moss2', 5.6), ('moss3', 5.6), ('moss4', 5.6)]
            for field, value in [('distance_filtered_cm', distance), ('measurement_stable', 1)]]


class TargetTests(unittest.TestCase):
    def test_target_uses_mount_minus_distance_without_platform_offset(self):
        result = water_overview(readings(), CONFIG, 11)
        self.assertAlmostEqual(result['target_cm'], 5)
        self.assertEqual(result['moss_distances_cm']['moss1'], 5.6)
        self.assertEqual(result['moss_distances_cm']['moss3'], 5.6)

    def test_missing_stale_unstable_or_impossible_moss_blocks_target(self):
        for data in [[], readings()[:2], readings(now=-10),
                     [dict(r, value=0) if r['field'] == 'measurement_stable' else r for r in readings()],
                     [dict(r, value=20) if r['field'] == 'distance_filtered_cm' else r for r in readings()]]:
            self.assertIsNone(water_overview(data, CONFIG, 11)['target_cm'])

    def test_shared_mounting_height_and_missing_mount(self):
        config = copy.deepcopy(CONFIG)
        config['moos']['montagehoehe_cm'] = 13.2
        self.assertAlmostEqual(water_overview(readings(), config, 11)['target_cm'], 5.1)
        config['moos']['montagehoehe_cm'] = None
        self.assertIsNone(water_overview(readings(), config, 11)['target_cm'])

    def test_target_capped_below_hard_limit_and_at_zero(self):
        config = copy.deepcopy(CONFIG)
        config['automatik']['wasser_unter_moosspitzen_cm'] = 0
        self.assertAlmostEqual(water_overview(readings(), config, 11)['target_cm'], 6.8)
        config['automatik']['wasser_unter_moosspitzen_cm'] = 20
        self.assertEqual(water_overview(readings(), config, 11)['target_cm'], 0)


class PumpTests(unittest.TestCase):
    def test_same_start_threshold_on_first_run_and_restart(self):
        pump = PumpRegulator()
        for now in (0, 30, 60): self.assertEqual(pump.value(state(4.9), OPTIONS, now), 0)
        self.assertEqual(pump.value(state(4.7), OPTIONS, 61), 0)
        self.assertEqual(pump.value(state(4.7), OPTIONS, 91), 25)
        self.assertEqual(pump.state, 'filling')
        self.assertEqual(pump.value(state(4.9), OPTIONS, 92), 25)
        self.assertEqual(pump.value(state(5), OPTIONS, 93), 0)
        self.assertEqual(pump.value(state(4.9), OPTIONS, 94), 0)

    def test_wave_at_normal_target_does_not_stop_filling_but_hard_limit_does(self):
        pump = PumpRegulator()
        pump.value(state(), OPTIONS, 0)
        self.assertEqual(pump.value(state(), OPTIONS, 30), 25)
        # A raw wave near the normal target has not crossed the independent hard limit.
        data = dict(state(4.8), raw_level_cm=5.1)
        self.assertEqual(pump.value(data, OPTIONS, 31), 25)
        data['pump_allowed'] = False
        self.assertEqual(pump.value(data, OPTIONS, 32), 0)
        self.assertEqual(pump.state, 'blocked')

    def test_sensor_fault_resets_start_confirmation(self):
        pump = PumpRegulator()
        pump.value(state(), OPTIONS, 0)
        self.assertEqual(pump.value(None, OPTIONS, 29), 0)
        self.assertEqual(pump.value(state(), OPTIONS, 30), 0)
        self.assertEqual(pump.value(state(), OPTIONS, 59), 0)
        self.assertEqual(pump.value(state(), OPTIONS, 60), 25)
        self.assertEqual(pump.value(dict(state(), target_cm=None), OPTIONS, 61), 0)
        self.assertFalse(pump_ready(dict(state(), water_ready=False)))
