import unittest

from temperature import combine


class TemperatureTests(unittest.TestCase):
    def test_humidity_uses_percent_and_same_sensor_priority(self):
        result = combine({('left', 'sht45'): 60, ('right', 'scd40'): 62}, '%')
        self.assertEqual(result['value'], 61)
        self.assertEqual(result['source'], 'L: 60,0%\nR: 62,0% (fallback)\n+2,0%')

    def test_prefers_sht45_and_averages_both_sides(self):
        result = combine({('left', 'sht45'): 20, ('right', 'sht45'): 22,
                          ('left', 'scd40'): 30})
        self.assertEqual(result['value'], 21)
        self.assertEqual(result['source'], 'L: 20,0°\nR: 22,0°\n+2,0°')
        self.assertNotIn('SCD40', result['source'])

    def test_fallback_and_missing_sides_are_identified(self):
        result = combine({('right', 'scd40'): 19.5})
        self.assertEqual(result['value'], 19.5)
        self.assertIn('L: –\nR: 19,5°', result['source'])
        self.assertIn('(fallback)', result['source'])
        self.assertIsNone(combine({})['value'])


if __name__ == '__main__':
    unittest.main()
