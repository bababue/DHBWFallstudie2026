"""Render current sensor readings in a dedicated OLED container."""

import json
import logging
import os
import socket
import time

from influxdb_client import InfluxDBClient

from oled import render


LOG = logging.getLogger("moos.oled")
SOCKET_PATH = "/run/moos-oled/frame.sock"


def latest_readings(client, bucket, org, max_age_seconds):
    query = (
        f"from(bucket: {json.dumps(bucket)})\n"
        f'  |> range(start: -{max_age_seconds}s)\n'
        '  |> filter(fn: (r) => r._measurement == "moos_sensor")\n'
        '  |> last()'
    )
    readings = {}
    for table in client.query_api().query(query, org=org):
        for record in table.records:
            readings[(record.values.get("side"), record.values.get("sensor"),
                      record.get_field())] = record.get_value()
    return readings


def send_frame(frame):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(SOCKET_PATH)
        connection.sendall(frame)
        if connection.recv(1) != b"\x01":
            raise OSError("OLED frame was not acknowledged")


def run():
    url = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
    org = os.getenv("INFLUXDB_ORG", "moos")
    bucket = os.getenv("INFLUXDB_BUCKET", "moos_sensors")
    max_age_seconds = int(os.getenv("DASHBOARD_MAX_AGE_SECONDS", "12"))
    if max_age_seconds < 5:
        raise ValueError("DASHBOARD_MAX_AGE_SECONDS must be >=5")
    token = os.environ["INFLUXDB_TOKEN"]
    with InfluxDBClient(url=url, token=token, org=org, timeout=5000) as client:
        while True:
            started = time.monotonic()
            try:
                send_frame(render(latest_readings(client, bucket, org, max_age_seconds)))
            except Exception as error:
                LOG.warning("OLED update failed: %s", error)
            time.sleep(max(0.05, 1.0 - (time.monotonic() - started)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
