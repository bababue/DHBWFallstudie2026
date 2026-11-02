#!/usr/bin/env python3
"""Move legacy hardware values into versioned config; retain secrets in .env."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import configuration

path = ROOT / 'config/config.json'
marker = ROOT / 'config/.env-migrated'
if not marker.exists():
    env_path = ROOT / '.env'
    if env_path.exists():
        lines = env_path.read_text().splitlines()
        values = dict(line.split('=', 1) for line in lines if '=' in line and not line.lstrip().startswith('#'))
        data = json.loads(path.read_text())
        for name, (group, key) in configuration.KEYS.items():
            if name in values:
                raw = values[name].strip().strip('\"\'')
                if not raw:
                    data[group][key] = None
                elif name.endswith('_GPIO') or name.endswith('_ADDRESS') or name == 'I2C_DELAY_US':
                    data[group][key] = int(raw, 0)
                else:
                    data[group][key] = float(raw)
        configuration.validate(data)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
        keep = {'GPIOCHIP_DEVICE', 'INFLUXDB_URL', 'INFLUXDB_ORG', 'INFLUXDB_BUCKET',
                'INFLUXDB_USERNAME', 'INFLUXDB_PASSWORD', 'INFLUXDB_TOKEN'}
        env_path.write_text('# InfluxDB credentials and connection; hardware settings: config/config.json\n' +
                            '\n'.join(line for line in lines if '=' in line and line.split('=', 1)[0] in keep) + '\n')
    marker.touch()
