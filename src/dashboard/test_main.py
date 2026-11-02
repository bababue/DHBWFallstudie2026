import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class DashboardTests(unittest.TestCase):
    def test_mode_follows_sensor_state_and_expires(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'mode.json'
            with patch.object(main, 'MODE_FILE', state):
                self.assertIsNone(main.mode()['mode'])
                state.write_text(json.dumps({'mode': 'MEASURING', 'updated': time.time()}))
                self.assertEqual(main.mode()['mode'], 'MEASURING')
                state.write_text(json.dumps({'mode': 'AUTO', 'updated': time.time() - 10}))
                self.assertIsNone(main.mode()['mode'])

    def test_page_has_mode_and_camera(self):
        body = main.index().body.decode()
        self.assertIn('Aktueller Modus', body)
        self.assertIn('/camera/stream.mjpg', body)
        self.assertNotIn('led-slider', body)


if __name__ == '__main__':
    unittest.main()
