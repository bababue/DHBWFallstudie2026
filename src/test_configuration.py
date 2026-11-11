import copy
import unittest
from configuration import load, validate, setting


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

    def test_manual_timeout_is_configured_in_hours(self):
        for value in (0, 169, True, '1'):
            data = copy.deepcopy(load())
            data['modus']['manuell_dauer_stunden'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(data)
        data = copy.deepcopy(load())
        data['modus']['manuell_dauer_stunden'] = 1.5
        validate(data)

    def test_ultrasonic_filter_requires_safe_valid_parameters(self):
        for key, value in [('messungen', 2), ('messungen', 102),
                           ('messungen', 15.0),
                           ('wasser_streuung_cm', 0), ('moos_streuung_cm', 5.1),
                           ('wasser_streuung_cm', True), ('max_messpause_s', 0),
                           ('max_messpause_s', 13), ('max_messpause_s', True)]:
            data = copy.deepcopy(load())
            data['ultraschall_glaettung'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate(data)
        data = copy.deepcopy(load())
        data['ultraschall_glaettung'].update(messungen=60,
                                             wasser_streuung_cm=.01, moos_streuung_cm=5)
        validate(data)

    def test_nested_moss_pins_are_checked_and_accessible(self):
        data = copy.deepcopy(load())
        self.assertEqual(setting('MOSS_1_TRIGGER_GPIO'), str(data['moos']['sensoren']['moos_1']['trigger_gpio']))
        data['moos']['sensoren']['moos_4']['trigger_gpio'] = data['wasserstand']['echo_gpio']
        with self.assertRaises(ValueError):
            validate(data)
        data = copy.deepcopy(load())
        data['moos']['sensoren']['moos_1']['extra'] = 1
        with self.assertRaises(ValueError):
            validate(data)

    def test_filter_gap_must_exceed_both_sample_intervals(self):
        data = copy.deepcopy(load())
        data['ultraschall_glaettung']['max_messpause_s'] = data['messintervalle']['moos_s']
        with self.assertRaises(ValueError):
            validate(data)

    def test_mounting_height_may_be_unset_but_must_be_positive(self):
        data = copy.deepcopy(load())
        data['moos']['montagehoehe_cm'] = None
        validate(data)
        data['moos']['montagehoehe_cm'] = -1
        with self.assertRaises(ValueError):
            validate(data)

    def test_actuator_gpio_collisions_and_invalid_frequency_are_rejected(self):
        data = copy.deepcopy(load())
        data['aktoren']['licht_gpio'] = data['taster']['gpio']
        with self.assertRaises(ValueError): validate(data)
        data = copy.deepcopy(load())
        data['aktoren']['licht_pwm_hz'] = 0
        with self.assertRaises(ValueError): validate(data)

    def test_maximum_must_be_below_water_sensor(self):
        data = copy.deepcopy(load())
        data['wasserstand']['max_fuellhoehe_cm'] = data['wasserstand']['sensor_boden_abstand_cm']
        with self.assertRaises(ValueError):
            validate(data)

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
