import copy
import unittest
from configuration import load, validate


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

    def test_fixed_target_requires_boolean_flag_and_valid_height(self):
        for value in ('true', 1, None):
            data = copy.deepcopy(load())
            data['automatik']['zielwasserstand_fest'] = value
            with self.assertRaises(ValueError):
                validate(data)
        for value in (-1, float('nan'), float('inf'), True, None):
            data = copy.deepcopy(load())
            data['automatik']['zielwasserstand_cm'] = value
            with self.assertRaises(ValueError):
                validate(data)
        data = copy.deepcopy(load())
        data['automatik'].update(zielwasserstand_fest=True, zielwasserstand_cm=0)
        validate(data)

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
