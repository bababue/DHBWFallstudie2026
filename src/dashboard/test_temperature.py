import unittest

from temperature import combine


class TemperatureTests(unittest.TestCase):
    def test_prefers_sht45_and_averages_both_sides(self):
        result = combine({('left', 'sht45'): 20, ('right', 'sht45'): 22,
                          ('left', 'scd40'): 30})
        self.assertEqual(result['value'], 21)
        self.assertIn('Unterschied', result['source'])
        self.assertNotIn('SCD40', result['source'])

    def test_fallback_and_missing_sides_are_identified(self):
        result = combine({('right', 'scd40'): 19.5})
        self.assertEqual(result['value'], 19.5)
        self.assertIn('Nur rechts', result['source'])
        self.assertIn('Backup', result['source'])
        self.assertIsNone(combine({})['value'])


if __name__ == '__main__':
    unittest.main()
