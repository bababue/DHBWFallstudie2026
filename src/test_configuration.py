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

    def test_demo_configuration_requires_boolean_and_valid_distance(self):
        data = copy.deepcopy(load())
        data['moos_demo']['demo_data'] = 'false'
        with self.assertRaises(ValueError): validate(data)
        data['moos_demo']['demo_data'] = True
        data['moos_demo']['demo_distance_2_cm'] = -1
        with self.assertRaises(ValueError): validate(data)

    def test_legacy_demo_distance_is_copied_to_each_sensor(self):
        data = copy.deepcopy(load())
        data['moos_demo'] = {'demo_data': True, 'demo_distance_cm': 7.2}
        upgraded = validate(upgrade(data))
        self.assertEqual([upgraded['moos_demo'][f'demo_distance_{i}_cm'] for i in range(1, 5)], [7.2] * 4)
        self.assertIn('demo_distance_cm', data['moos_demo'])

    def test_individual_demo_distances_are_preserved(self):
        data = copy.deepcopy(load())
        for i in range(1, 5):
            data['moos_demo'][f'demo_distance_{i}_cm'] = float(i + 5)
        result = validate(upgrade(data))
        self.assertEqual([result['moos_demo'][f'demo_distance_{i}_cm'] for i in range(1, 5)], [6, 7, 8, 9])
