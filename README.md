# Moos-Pi

Steuerung und Anzeige für den Mooskasten auf einem Raspberry Pi 5. Docker Compose
startet Sensoren, Dashboard, Kamera und InfluxDB.

## Start auf dem Raspberry Pi

Im Projektverzeichnis:

```sh
cp .env.example .env
```

`.env` enthält InfluxDB-Zugangsdaten
und `GPIOCHIP_DEVICE`. Ändere die Beispiel-Zugangsdaten, bevor du eine neue
Installation öffentlich erreichbar machst. Für eine bestehende InfluxDB müssen
Token, Organisation und Bucket zu der vorhandenen Datenbank passen. InfluxDB
wendet die Init-Werte nur beim ersten Anlegen des Datenverzeichnisses an.

Dann starten:

```sh
docker compose up -d --build
docker compose logs -f sensors dashboard
```

Dashboard: <http://moos.local:8080> (oder `http://<IP-des-Pi>:8080`).
InfluxDB: <http://moos.local:8086>. Mit `Ctrl-C` endet die Log-Anzeige; die
Container laufen weiter. Anhalten und wieder starten:

```sh
docker compose down
docker compose up -d
```

`./start.sh` aktualisiert zuerst den Checkout mit `git pull --ff-only` und baut
dann die Compose-Container neu. Das Skript eignet sich für einen sauberen
Checkout ohne lokale Änderungen.

## Bedienung

Der Taster an GPIO 26 wechselt mit kurzem Druck zwischen `AUTO` und `MANUAL`.
Gedrückthalten zeigt die Sensorübersicht. Nach einem Neustart startet das System
in `AUTO`. Der Modus lässt sich auch im Dashboard umschalten.

- **AUTO:** Licht und Temperatur werden automatisch geregelt. Die Pumpe bleibt
  zunächst gesperrt. „Automatische Pumpe freigeben“ einschalten und den Dialog
  bestätigen. Nach jedem Moduswechsel in AUTO oder Neustart erneut freigeben.
- **MANUAL:** Lüfter, Pumpe und Licht lassen sich im Dashboard einstellen.
  Die Wasserstands-Sperre für die Pumpe gilt in beiden Modi.

Die Sensorwerte werden auch in MANUAL aufgezeichnet. Messwerte, die nicht neu
eintreffen, werden nicht als aktuell weiterverwendet.

## Konfiguration

Hardware und Sollwerte stehen in `config/config.json`; Zugangsdaten stehen in
`.env`. Die Konfigurationsdatei wird in die Container nur lesbar eingebunden.
Die Sensoren liefern ausschließlich echte Messungen. Details zum Aufbau stehen
in [HARDWARE.md](HARDWARE.md).

Die Moossensoren messen direkt den Abstand ab Decke. Pro Sensor steht unter
`montagehoehe_cm` der Abstand seiner Sensorfläche zum Tankboden; übernommen
wurden 12,94 cm und 12,059 cm. `null` bedeutet: noch nicht für Bewässerung eingerichtet.
Das Ziel liegt 2,5 cm unter der aus diesen Abständen berechneten Moosoberfläche.
Die Pumpe startet nach 30 Sekunden bestätigt niedrigem Wasserstand und stoppt
am gefilterten Ziel. Ein Rohwasserstand ab 7 cm sperrt sie sofort.
Filter- und Zeitgrenzen stehen gesammelt in `src/measurements.py`.

Änderungen an Sensorpins oder Intervallen starten `sensors`
automatisch neu. Einstellungen in `automatik` werden live gelesen. Nach einer
Änderung an Aktor-GPIOs oder PWM-Frequenzen Dashboard und Sensorprozess neu
starten:

```sh
docker compose restart sensors dashboard
```

Die Software validiert Konfigurationsstruktur, Wertebereiche und doppelte
GPIO-Belegungen.

Die Wasserstands-Pumpensperre benötigt eine konfigurierte maximale Füllhöhe und
einen höchstens drei Sekunden alten Messwert. Fehlende oder ungültige Werte
sperren die Pumpe. Die maximale Füllhöhe gilt auch in MANUAL.
Diese Software-Sperre ersetzt keinen unabhängigen Schwimmerschalter.

## Kalibrierung

Kalibrierungsskripte auf dem Pi im Projektverzeichnis ausführen. Sie halten den
Sensorcontainer während der Messung an und starten ihn danach wieder, sofern er
zuvor lief.

```sh
python3 scripts/calibrate_water.py
python3 scripts/calibrate_co2.py
```

Wasserstand: Behälter leeren, ruhige Oberfläche und freien Schallweg sicherstellen.
Optional kann eine bekannte Wassertiefe angegeben werden, z. B.
`--water-height 1.5`. Moos-Montagehöhen direkt vom Sensor bis zum Tankboden messen.
CO₂: Kasten geöffnet draußen aufstellen; ein Referenzmessgerät ist genauer als
die Voreinstellung von 430 ppm. Die Skripte fragen vor dem Speichern nach einer
Bestätigung.

Die Wasserstands-Kalibrierung speichert den Bodenabstand in
`config/config.json`. Eine Papierkalibrierung für Moossensoren ist nicht erforderlich.

## Diagnose

Prüfsummen der SHT45- und SCD40-Messwerte sowie je drei rohe Abstandsmessungen
prüfen:

```sh
python3 scripts/check_sensors.py
```

Falls das Sensor-Image noch fehlt, zuerst `docker compose build sensors`
ausführen. Die Diagnose stoppt Dashboard und Sensorprozess während des Zugriffs
auf die GPIOs und startet nur zuvor laufende Dienste danach wieder. BH1750 und
Ultraschallsensoren unterstützen keine CRC-Prüfung. Die Mittelwerte gelten nur
für dieses Skript; Produktionsfilter und Kalibrierung bleiben unverändert.

```sh
docker compose ps
docker compose logs -f sensors
docker compose logs -f dashboard
docker compose logs -f camera
```

Bei Sensor- oder Dashboard-Änderungen hilft ein Neubau der Container:
`docker compose up -d --build`. Messdaten liegen im Compose-Volume
`influxdb-data`; `.env` wird nicht versioniert. Uncommittete Änderungen können
`./start.sh` und den optionalen Auto-Deploy blockieren.

## Tests

Getrennte `unittest`-Läufe vermeiden Namenskonflikte zwischen den Modulen
`main.py`:

```sh
python3.13 -m venv /tmp/moos-tests
/tmp/moos-tests/bin/pip install fastapi httpx influxdb-client
PATH="/tmp/moos-tests/bin:$PATH" scripts/test.sh
```

Weitere technische Details stehen in [docs/TECHNIK.md](docs/TECHNIK.md).
Optionale systemd-Bereitstellung: [deploy/README.md](deploy/README.md).
