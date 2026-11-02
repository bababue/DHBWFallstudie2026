import copy
import unittest
from configuration import load, upgrade, validate


class ConfigurationTests(unittest.TestCase):
    def test_current_configuration_valid(self):
        validate(load())

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

    def test_legacy_config_migrates_demo_without_changing_reference(self):
        data = copy.deepcopy(load())
        for i in range(1, 5):
            del data[f'moos_{i}']['demo']
        data['moos_1']['bezugsabstand_cm'] = None
        data['moos_demo'] = {'demo_data': True, 'demo_distance_1_cm': 7.2}
        result = validate(upgrade(data))
        self.assertTrue(result['moos_1']['demo'])
        self.assertIsNone(result['moos_1']['bezugsabstand_cm'])
        self.assertNotIn('moos_demo', result)
        self.assertIn('moos_demo', data)

    def test_lid_threshold_defaults_and_validation(self):
        data = copy.deepcopy(load())
        del data['deckel']
        self.assertEqual(validate(upgrade(data))['deckel']['offen_abstand_cm'], 12.0)
        data = upgrade(data)
        data['deckel']['offen_abstand_cm'] = 0
        with self.assertRaises(ValueError): validate(data)
