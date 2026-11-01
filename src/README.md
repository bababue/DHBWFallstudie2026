# Grafana und InfluxDB

Beide Dienste werden zusammen mit dem Sensor-Ingest aus der
[Compose-Datei im Repository-Root](../compose.yaml) gestartet. Ihre Daten
liegen in den benannten Compose-Volumes `grafana-data`, `influxdb-data` und
`influxdb-config`. Die Datenquelle wird aus
`grafana/provisioning/datasources/influxdb.yaml` eingerichtet. Das Dashboard
liegt in `grafana/provisioning/dashboards/moos-sensors.json`.

Einrichtung, Start und Flux-Abfragen stehen in der
[README im Repository-Root](../README.md).
