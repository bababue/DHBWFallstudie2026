import copy
import unittest
from configuration import load, validate


class ConfigurationTests(unittest.TestCase):
    def test_current_configuration_valid(self):
        validate(load())

    def test_pump_schedule_requires_both_times_and_rejects_invalid_time(self):
        data = copy.deepcopy(load())
        del data['automatik']['pumpe_start_stunde']
        with self.assertRaises(ValueError): validate(data)
        for key, value in [('pumpe_start_stunde', 24), ('pumpe_start_minute', 60), ('pumpe_start_minute', 1.5)]:
            invalid = copy.deepcopy(load())
            invalid['automatik'][key] = value
            with self.assertRaises(ValueError):
                validate(invalid)

    def test_rejects_gpio_collisions_and_unknown_fields(self):
        data = copy.deepcopy(load())
        data['taster']['gpio'] = data['wasserstand']['echo_gpio']
        with self.assertRaises(ValueError): validate(data)
        data = copy.deepcopy(load())
        data['password'] = 'not allowed'
        with self.assertRaises(ValueError): validate(data)

    def test_rejects_invalid_interval(self):
        data = copy.deepcopy(load())
        data['messintervalle']['schnelle_sensoren_s'] = 0
        with self.assertRaises(ValueError): validate(data)

    def test_demo_flags_must_be_boolean_and_allow_missing_reference(self):
        data = copy.deepcopy(load())
        for i in range(1, 5):
            data[f'moos_{i}']['demo'] = True
            data[f'moos_{i}']['bezugsabstand_cm'] = None
        validate(data)
        data['moos_2']['demo'] = 'true'
        with self.assertRaises(ValueError): validate(data)

    def test_legacy_config_fields_are_rejected(self):
        data = copy.deepcopy(load())
        data['moos_demo'] = {'demo_data': True}
        with self.assertRaises(ValueError): validate(data)
        data = copy.deepcopy(load())
        data['deckel'] = {'offen_abstand_cm': 12.0}
        with self.assertRaises(ValueError): validate(data)

    def test_demo_distance_is_validated_without_defaults(self):
        data = copy.deepcopy(load())
        data['moos_1']['bezugsabstand_cm'] = 6.94
        data['moos_1']['demo_abstand_cm'] = 7.94
        data['moos_2']['bezugsabstand_cm'] = None
        data['moos_2']['demo_abstand_cm'] = None
        result = validate(data)
        self.assertEqual(result['moos_1']['demo_abstand_cm'], 7.94)
        self.assertIsNone(result['moos_2']['demo_abstand_cm'])
        result['moos_1']['demo_abstand_cm'] = -1
        with self.assertRaises(ValueError): validate(result)

    def test_actuator_gpio_collisions_and_invalid_frequency_are_rejected(self):
        data = copy.deepcopy(load())
        data['aktoren']['licht_gpio'] = data['taster']['gpio']
        with self.assertRaises(ValueError): validate(data)
        data = copy.deepcopy(load())
        data['aktoren']['licht_pwm_hz'] = 0
        with self.assertRaises(ValueError): validate(data)

    def test_water_margin_must_be_below_maximum(self):
        data = copy.deepcopy(load())
        data['wasserstand']['max_fuellhoehe_cm'] = 6
        data['wasserstand']['sicherheitsabstand_cm'] = 6
        with self.assertRaises(ValueError): validate(data)

    def test_light_schedule_requires_configuration_and_valid_values(self):
        data = copy.deepcopy(load())
        del data['automatik']
        with self.assertRaises(ValueError): validate(data)
        for key, value in [('licht_start_stunde', 24), ('lichtdauer_stunden', 0),
                           ('lichtstaerke_prozent', 101), ('lichtstaerke_prozent', 1)]:
            data = copy.deepcopy(load())
            data['automatik'][key] = value
            with self.assertRaises(ValueError): validate(data)

    def test_pump_settings_reject_invalid_target_and_duty(self):
        for key, value in [('wasser_unter_moosspitzen_cm', -1), ('pumpe_hysterese_cm', 0),
                           ('pumpe_leistung_prozent', 1)]:
            data = copy.deepcopy(load())
            data['automatik'][key] = value
            with self.assertRaises(ValueError): validate(data)
