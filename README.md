# Moos-Pi

Dashboard und Steuerung für einen Mooskasten auf dem Raspberry Pi 5.
Sensoren, Licht, Lüfter, Kamera und InfluxDB laufen über Docker Compose.
Die Pumpe ist derzeit softwareseitig deaktiviert.

## Start und Updates

Beim ersten Start im Projektverzeichnis:

```sh
cp .env.example .env
```

In `.env` eigene InfluxDB-Zugangsdaten eintragen und `GPIOCHIP_DEVICE` prüfen.
Bei einer bestehenden Datenbank müssen Token, Organisation und Bucket dazu passen;
die InfluxDB-Initialisierung greift nur bei einem neuen Datenverzeichnis.

```sh
docker compose up -d --build
```

- Dashboard: <http://moos.local:8080>
- InfluxDB: <http://moos.local:8086>

`moos.local` bei Bedarf durch die IP des Pi ersetzen. Die Kamera ist im Dashboard
integriert. Messdaten bleiben im Docker-Volume `influxdb-data` gespeichert.

Updates aus dem Repository holen und Container neu bauen:

```sh
./start.sh
```

Das Skript führt `git pull --ff-only` aus. Änderungen müssen zuvor committed
und gepusht sein; lokale Änderungen auf dem Pi können das Update blockieren.
Nach direkt auf den Pi übertragenen Codeänderungen genügt
`docker compose up -d --build`.

## Bedienung

Das OLED zeigt dauerhaft Messwerte und Modus. Der Taster an GPIO 26 sowie der
Schalter im Dashboard wechseln zwischen:

- **AUTO:** Licht und Lüfter werden automatisch geregelt.
- **MANUAL:** Licht und Lüfter sind im Dashboard einstellbar. Nach einer Stunde
  schaltet das System automatisch auf AUTO zurück.

Nach einem Neustart beginnt das System in AUTO. Sensoren messen in beiden Modi.

## Automatische Regelung

Die Lichtphase läuft standardmäßig von 06:00 bis 22:00 Uhr, mit jeweils
20 Minuten zum Ein- und Ausblenden. Das Lichtmaximum beträgt 100 %.
Bei 20,5 °C sind außerhalb der Übergangszeiten damit 100 % möglich.

Die wärmere Seite bestimmt die Temperaturregelung. Ab dem Zielwert von 22 °C
steigt die Lüfterleistung proportional an und das Licht wird heruntergedimmt.
Normale Stellwertänderungen laufen in einzelnen Prozentpunkten mit maximal
2 Prozentpunkten pro Sekunde; die Temperatur wird dafür geglättet.
Der Lüfter erhält beim Anlaufen einen Stoß von 0,5 Sekunden.

Ab 25 °C oder bei fehlender Temperaturmessung einer Seite schaltet AUTO sofort
auf Licht aus und Lüfter 100 %. Nach Überhitzung erfolgt die Freigabe erst unter
24 °C. Diese Temperaturregelung gilt im AUTO-Modus.

## Konfiguration und Messwerte

Pins, Messintervalle und Sollwerte stehen in [`config/config.json`](config/config.json),
Zugangsdaten in `.env`. Die wichtigsten Bereiche:

| Bereich | Inhalt |
|---|---|
| `automatik` | Lichtzeiten, Lichtmaximum und Temperaturregelung |
| `modus.manuell_dauer_stunden` | Laufzeit des manuellen Modus |
| `wasserstand`, `moos` | Ultraschallpins und Montagehöhen |
| `ultraschall_glaettung` | Fenstergröße und erlaubte Streuung |
| `demo` | Demo-Anzeige der Mooshöhe |

Konfigurationsänderungen werden erkannt und starten den Sensorprozess neu.
Nach Änderungen an Aktor-Pins oder PWM-Frequenzen zusätzlich neu starten:

```sh
docker compose restart sensors dashboard
```

Die Ultraschallfilter sammeln je Sensor 60 Messungen. Verwendet werden Werte
innerhalb von ±0,2 cm (Wasser) beziehungsweise ±0,3 cm (Moos) um den Median.
Nach fehlendem Echo beginnt das Sammeln neu. Erste geglättete Werte brauchen
etwa eine Minute für Wasser und vier Minuten für Moos.

Das Dashboard zeigt Wasserhöhe, den Median der vier verfügbaren Mooshöhen,
Temperatur, Luftfeuchtigkeit, CO₂ und Licht. Einzelwerte und Filteranteile stehen
in der Debug-Tabelle. Details zur Messung: [docs/TECHNIK.md](docs/TECHNIK.md).

**Die Demo-Anzeige ist aktuell aktiviert:** `demo.aktiv: true` zeigt die Mooshöhe
als Wasserhöhe plus `demo.moos_ueber_wasser_cm` (2 cm) und kennzeichnet sie als
„Demo“. Mit `false` erscheint der echte Moos-Median. Ohne gültige Wasserhöhe
gibt es keinen Demo-Wert. Speicherung und Aktorsteuerung verwenden echte Daten.

## Diagnose und Kalibrierung

```sh
docker compose ps
docker compose logs --tail 100 sensors dashboard camera
python3 scripts/check_sensors.py
python3 scripts/calibrate_water.py
python3 scripts/calibrate_co2.py
```

Die Python-Skripte starten ihre Hardwarezugriffe in Docker und halten dafür die
betroffenen Container vorübergehend an. Wasserstand bei leerem Behälter oder mit
`--water-height <cm>` kalibrieren. Für CO₂ den geöffneten Kasten in Außenluft
stellen; eine bekannte Referenz kann mit `--reference <ppm>` angegeben werden.
Die Kalibrierungsskripte fragen vor dem Speichern nach Bestätigung.
Hardware und Verdrahtung: [HARDWARE.md](HARDWARE.md).

## Tests ohne Hardware

```sh
python3.13 -m venv /tmp/moos-tests
/tmp/moos-tests/bin/pip install fastapi httpx influxdb-client
PYTHON=/tmp/moos-tests/bin/python scripts/test.sh
```

Die Tests prüfen die Softwarelogik; die Wirkung am realen Aufbau muss separat
beobachtet werden.
