# Moos Fallstudie auf dem Raspberry Pi

Das Projekt läuft mit Docker Compose: `ingest` liest den Abstandssensor (Trigger GPIO 5, Echo GPIO 6) und den SCD41-CO₂-Sensor über I²C. Beide Werte erscheinen auf dem OLED und in den Container-Logs. `influxdb` und `grafana` laufen im selben Compose-Projekt. Die Visualisierungsdaten liegen unter `src/visualisation/`.

## Einmalige Umstellung auf dem Pi

Docker Engine und das Compose-Plugin müssen auf dem Pi mit einem 64-Bit-System installiert sein. Das folgende Setup geht vom Checkout unter `/home/moos/DHBWFallstudie2026` aus. Bisherige Host-Dienste für Sensor und Updates müssen vor dem Start der Container abgeschaltet sein. Falls die bisherige Visualisierung schon läuft, deren Container vor dem Pull stoppen; die eingebundenen Datenverzeichnisse bleiben dabei erhalten:

```bash
cd /home/moos/DHBWFallstudie2026
sudo docker compose --env-file src/visualisation/.env -f src/visualisation/compose.yaml down
git pull --ff-only origin master
```

Wer die alte Visualisierung nie gestartet hat, lässt die `docker compose ... down`-Zeile aus. Sie muss vor dem `git pull` ausgeführt werden, weil die alte Compose-Datei danach entfernt ist.

Die bisherige `.env` für Grafana und InfluxDB liegt eventuell noch unter `src/visualisation/.env`. Sie muss für die neue Root-Compose-Datei in den Root-Ordner:

```bash
cp src/visualisation/.env .env
```

Falls es keine bisherige `.env` gibt, `cp .env.example .env` ausführen und in `.env` `INFLUXDB_PASSWORD`, `INFLUXDB_ADMIN_TOKEN` sowie `GRAFANA_ADMIN_PASSWORD` setzen. Die `.env` wird nicht in Git eingecheckt. Bei abweichender Benutzer-ID für Grafana `GRAFANA_UID` und `GRAFANA_GID` anpassen.

Für OLED und SCD41 muss I²C auf dem Pi aktiviert sein. Beide nutzen denselben I²C-Bus; der SCD41 hat standardmäßig Adresse `0x62`, das OLED hier `0x3C`. Das Python-Skript öffnet für den SCD41 direkt `/dev/i2c-1`, damit im Container keine Board-Erkennung nötig ist. Der Container erhält diesen Bus sowie den GPIO-Chip. Für einen aktuellen Pi 5 ist `/dev/gpiochip0` voreingestellt; falls der zuständige Chip auf diesem Pi `/dev/gpiochip4` heißt, `GPIOCHIP_DEVICE=/dev/gpiochip4` in `.env` setzen. Die Echo-Leitung des Abstandssensors darf am GPIO nur 3,3 V liefern. Der erste CO₂-Wert erscheint nach etwa fünf Sekunden.

Dann die Container starten:

```bash
sudo ./start.sh
```

Auch für spätere Updates `sudo ./start.sh` aus dem Repository-Root ausführen. Das Skript zieht den Branch `master`, baut das Python-Image und startet die Container. Updates werden manuell angestoßen; die gestarteten Container nutzen `restart: unless-stopped`.

## Betrieb

```bash
sudo docker compose ps
sudo docker compose logs -f ingest
sudo docker compose logs -f grafana influxdb
```

Grafana: `http://<pi-ip>:3000` · InfluxDB: `http://<pi-ip>:8086`.
