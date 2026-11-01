import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main import READINGS, Settings, read_latest, render_page


class DashboardTests(unittest.TestCase):
    def test_plain_page_contains_every_sensor_value(self):
        values = {("left", "scd40", "co2_ppm"): 512.0}
        page = render_page(values, 30)
        self.assertEqual(page.count("<tr><td>"), len(READINGS))
        self.assertIn("SCD40 links – CO₂</td><td>512 ppm", page)
        self.assertIn("BH1750 rechts – Licht</td><td>kein aktueller Wert", page)
        self.assertNotIn("<style", page)
        self.assertNotIn("stylesheet", page)

    def test_queries_recent_raw_points_and_maps_tags(self):
        record = SimpleNamespace(
            values={"side": "right", "sensor": "sht45"},
            get_field=lambda: "temperature_c",
            get_value=lambda: 21.25,
        )
        client = unittest.mock.MagicMock()
        client.__enter__.return_value = client
        client.query_api.return_value.query.return_value = [SimpleNamespace(records=[record])]
        settings = Settings("http://influxdb:8086", "moos", "moos_sensors", "test-token", 30, 180)
        with patch("main.InfluxDBClient", return_value=client):
            values = read_latest(settings)
        self.assertEqual(values[("right", "sht45", "temperature_c")], 21.25)
        query = client.query_api.return_value.query.call_args.args[0]
        self.assertIn('range(start: -180s)', query)
        self.assertIn('last()', query)
        self.assertNotIn('aggregateWindow', query)


if __name__ == "__main__":
    unittest.main()
