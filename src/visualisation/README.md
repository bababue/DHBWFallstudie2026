# Grafana und InfluxDB

Die Compose-Datei bindet die Daten und Konfiguration direkt aus diesem Ordner ein:

- `grafana/data` → `/var/lib/grafana`
- `grafana/provisioning` → `/etc/grafana/provisioning` (nur lesbar)
- `influxdb/data` → `/var/lib/influxdb2`
- `influxdb/config` → `/etc/influxdb2`

Vor dem ersten Start auf dem Pi:

```bash
cd /home/moos/DHBWFallstudie2026/src/visualisation
cp .env.example .env
# INFLUXDB_PASSWORD, INFLUXDB_ADMIN_TOKEN und GRAFANA_ADMIN_PASSWORD in .env setzen.
# Falls moos nicht UID/GID 1000 hat, GRAFANA_UID und GRAFANA_GID anpassen.
docker compose up -d
```

Grafana ist danach unter `http://<pi-ip>:3000` erreichbar, InfluxDB unter
`http://<pi-ip>:8086`. Die Datenverzeichnisse und `.env` bleiben außerhalb
der Git-Versionierung.
