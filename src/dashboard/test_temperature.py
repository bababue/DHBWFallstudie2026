import unittest

from temperature import combine


class TemperatureTests(unittest.TestCase):
    def test_light_difference_uses_unrounded_values(self):
        result = combine({('left', 'bh1750'): 11.68, ('right', 'bh1750'): 17.52}, 'lx')
        self.assertAlmostEqual(result['value'], 14.6)
        self.assertEqual(result['source'], 'L: 11,7lx\nR: 17,5lx\n+50,0%')

    def test_co2_uses_scd40_as_primary(self):
        result = combine({('left', 'scd40'): 500, ('right', 'scd40'): 600,
                          ('left', 'sht45'): 20}, 'ppm')
        self.assertEqual(result['value'], 550)
        self.assertNotIn('fallback', result['source'])
        self.assertEqual(result['source'].splitlines()[-1], '+20,0%')

    def test_humidity_uses_percent_and_same_sensor_priority(self):
        result = combine({('left', 'sht45'): 60, ('right', 'scd40'): 62}, '%')
        self.assertEqual(result['value'], 61)
        self.assertEqual(result['source'], 'L: 60,0%\nR: 62,0% (fallback)\n+3,3%')

    def test_prefers_sht45_and_averages_both_sides(self):
        result = combine({('left', 'sht45'): 20, ('right', 'sht45'): 22,
                          ('left', 'scd40'): 30})
        self.assertEqual(result['value'], 21)
        self.assertEqual(result['source'], 'L: 20,0°\nR: 22,0°\n+10,0%')
        self.assertNotIn('SCD40', result['source'])

    def test_fallback_and_missing_sides_are_identified(self):
        result = combine({('right', 'scd40'): 19.5})
        self.assertEqual(result['value'], 19.5)
        self.assertIn('L: –\nR: 19,5°', result['source'])
        self.assertIn('(fallback)', result['source'])
        self.assertIsNone(combine({})['value'])

    def test_relative_difference_handles_zero_and_lower_right_value(self):
        zero = combine({('left', 'bh1750'): 0, ('right', 'bh1750'): 10}, 'lx')
        self.assertEqual(zero['source'].splitlines()[-1], '–')
        lower = combine({('left', 'scd40'): 500, ('right', 'scd40'): 400}, 'ppm')
        self.assertEqual(lower['source'].splitlines()[-1], '-20,0%')


if __name__ == '__main__':
    unittest.main()
