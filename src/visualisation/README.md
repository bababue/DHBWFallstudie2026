# Grafana und InfluxDB

Beide Dienste werden zusammen mit dem Sensor aus der [Compose-Datei im Repository-Root](../../compose.yaml) gestartet. Die persistenten Daten bleiben in diesem Ordner:

- `grafana/data` → `/var/lib/grafana`
- `grafana/provisioning` → `/etc/grafana/provisioning` (nur lesbar)
- `influxdb/data` → `/var/lib/influxdb2`
- `influxdb/config` → `/etc/influxdb2`

Einrichtung und Start stehen in der [README im Repository-Root](../../README.md).
