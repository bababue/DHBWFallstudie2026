# Moos-Pi: Sensoren

Der `sensors`-Container liest auf dem Raspberry Pi 5 die drei I2C-Sensoren links
und rechts sowie fünf Ultraschallsensoren für Wasserstand und Mooshöhe. Er schreibt
ihre Messwerte in InfluxDB 2; das Dashboard zeigt sie an.

## Konfiguration

Alle Pins (BCM-Nummern), I2C-Adressen, die Abtastintervalle und die InfluxDB-
Zugangsdaten stehen in `.env`. Die Vorlage ist `.env.example`.

`sensors` liest SHT45, BH1750 und den Wasserstandsensor unabhängig voneinander
etwa jede Sekunde. Beim SCD40 prüft es alle 0,5 Sekunden, ob ein neuer CO₂-Wert
bereitliegt; der Sensor selbst erzeugt nur etwa alle 5 Sekunden einen neuen Wert.
Zwischen diesen Messungen wird kein alter CO₂-Wert erneut gespeichert.
Datenbank-Schreibvorgänge laufen getrennt von den GPIO-Abfragen. Das Dashboard
fragt InfluxDB alle 0,5 Sekunden ab und zeigt Werte nach 12 Sekunden ohne neues
Sample nicht mehr als aktuell an. Der Sensorprozess aktualisiert das OLED etwa
einmal pro Sekunde direkt aus den letzten Messwerten.

```sh
cp .env.example .env
```

Die Vorlage enthält `ohnemoosnixlos` als InfluxDB-Passwort sowie
einen Beispieltoken für eine **neue** InfluxDB-Installation. Die Datei `.env`
ist von Git ausgeschlossen. Für einen bestehenden InfluxDB-Datenbestand muss
`INFLUXDB_TOKEN` in `.env` mit einem dort bereits gültigen Token übereinstimmen:
Neue Initialisierungswerte ändern bestehende Benutzer, Passwörter oder Tokens
nicht. Die Vorlage aktiviert die Aktorsteuerung.

| Seite | SDA | SCL | Sensoren |
| --- | ---: | ---: | --- |
| links | GPIO 15 | GPIO 14 | SHT45 `0x44`, BH1750/GY-302 `0x23`, SCD40 `0x62` |
| rechts | GPIO 23 | GPIO 24 | SHT45 `0x44`, BH1750/GY-302 `0x23`, SCD40 `0x62` |

Der Wasserstandsensor nutzt Trigger GPIO 6 und Echo GPIO 13. Aus dem gemessenen
Abstand zur Wasseroberfläche und dem Sensor-Boden-Abstand von 8,62 cm berechnet
die Software die Wassertiefe in cm. Zusätzlich erscheint der Median der
Wassertiefe aus allen gültigen Echos der letzten 60 Sekunden. Der gemessene
Abstand (Median der Echos des aktuellen Messzyklus) bleibt als Rohwert sichtbar.
Beim Start nutzt der Minutenmedian die bereits verfügbaren Messungen. Ohne Echo
erscheint kein aktueller Wert.
Die Echo-Leitung muss am Pi-Eingang auf höchstens 3,3 V begrenzt sein.

Vier zusätzliche Ultraschallsensoren messen den Abstand zur Moosoberfläche:

| Sensor | Trigger | Echo | Kalibrierwert in `.env` |
| --- | ---: | ---: | --- |
| Moos 1 | GPIO 0 | GPIO 5 | `MOSS_1_EMPTY_DISTANCE_CM` |
| Moos 2 | GPIO 9 | GPIO 11 | `MOSS_2_EMPTY_DISTANCE_CM` |
| Moos 3 | GPIO 22 | GPIO 10 | `MOSS_3_EMPTY_DISTANCE_CM` |
| Moos 4 | GPIO 17 | GPIO 27 | `MOSS_4_EMPTY_DISTANCE_CM` |

Jeder Kalibrierwert ist der Abstand vom Sensor zur moosfreien Bezugsfläche in cm.
Ohne ihn wird nur der Rohabstand angezeigt. Mit ihm berechnet die Software die
Mooshöhe je Messstelle. Je Sensor werden drei Echos pro Messzyklus gefiltert;
die Sensoren starten um eine Sekunde versetzt und messen jeweils alle vier Sekunden.
Für den gemeinsamen Wert nimmt die Software den Median der 60-Sekunden-Mediane
von mindestens drei gültigen, kalibrierten Messstellen. So beeinflusst ein
einzelner Ausreißer das Ergebnis wenig, und unterschiedliche Montagehöhen werden
über die einzelnen Kalibrierwerte berücksichtigt.

Die Busse sind Software-I2C. Der Code treibt eigene High-Bits aktiv, wie in der
Übergabe für diesen Aufbau beschrieben; das ist nur bei geprüfter 3,3-V-Verdrahtung
vertretbar. Der `sensors`-Container muss exklusiven Zugriff auf die vier I2C-Pins
und alle zehn Ultraschall-Pins haben. Eine andere Steuerung, die dieselben GPIOs benutzt, darf nicht
gleichzeitig laufen.

## OLED-Anzeige

Das SSD1306-OLED (128 × 64, Adresse `0x3C`) hängt am linken Sensorbus und ist um
180° gedreht. `sensors` rendert die Anzeige direkt aus seinen Messwerten und
greift als einziger Container auf GPIO 14 und 15 zu.

Das Display zeigt ausschließlich eine Sensorübersicht: links und rechts
Temperatur und Luftfeuchte vom SHT45,
CO₂ vom SCD40 sowie Helligkeit vom BH1750. Falls ein SHT45-Wert fehlt, dient
der entsprechende SCD40-Wert als Backup. Der eingebaute Taster an GPIO 26 wird
von der Docker-Software nicht verwendet. Licht, Pumpe und Lüfter werden ausschließlich
über das Web-Dashboard eingestellt.

## Start

Auf dem Pi mit Docker Compose:

```sh
# Einmalig bei einer Migration vom alten Aufbau:
sudo systemctl disable --now kamera-live moos-steuerung

./start.sh
docker compose logs -f sensors dashboard
```

`start.sh` holt zuerst die neuesten Git-Änderungen mit `git pull --ff-only`
und startet danach die Container mit frischen Images. Wenn lokale Änderungen
einen Pull verhindern, stoppt das Skript vor dem Docker-Start.

Der frühere Dienst `kamera-live` belegt Port 8000 und die Kamera;
`moos-steuerung` nutzt dieselben GPIO-Pins wie die Docker-Steuerung. Falls
Port 8000 weiterhin belegt ist, zeigt `sudo ss -ltnp '( sport = :8000 )'`
den Prozess. Die Abschaltung der alten Dienste ist nur einmalig nötig.
`--remove-orphans` entfernt beim Umstieg frühere Container.

Die Container heißen `sensors`, `influxdb`, `dashboard` und `camera`.
Sensoren, OLED, Steuerung und Kamera laufen vollständig in Docker Compose.

Das einfache Dashboard ist unter `http://moos.local:8080` erreichbar. Es ordnet
die aktuellen Werte nach Temperatur, Luftfeuchte, Licht und CO₂ und zeigt
links und rechts nebeneinander, weiterhin ohne CSS. Der Browser
lädt die Seite einmal und erhält neue Werte über eine WebSocket-Verbindung.
Der Server prüft InfluxDB alle 0,5 Sekunden und sendet Änderungen sofort an alle
verbundenen Browser. Messwerte, die älter als 12 Sekunden sind, erscheinen als
„kein aktueller Wert“. Die Zeiten lassen sich in `.env` über
`DASHBOARD_POLL_SECONDS` und `DASHBOARD_MAX_AGE_SECONDS` ändern. Bei einer
unterbrochenen Verbindung verbindet sich der Browser automatisch neu.

Auf derselben Seite erscheint der MJPEG-Livestream der Pi-Kamera. Der
`camera`-Container startet `rpicam-vid` erst, wenn ein Browser den Stream
öffnet, und gibt die Kamera nach dem letzten Zuschauer wieder frei. Der Stream
ist über `http://moos.local:8080/camera/stream.mjpg` erreichbar. Der Kamera-Port
ist nur im Compose-Netz erreichbar; `CAMERA_PORT` in `.env` legt ihn intern fest.
Für den Kamerazugriff erhält der Container
Zugriff auf die Pi-Geräte; der `dashboard`-Container nutzt GPIO 16, 20 und 21.

Die Regler für Licht, Lüfter und Pumpe senden ihre Werte über dieselbe
WebSocket-Verbindung wie die Sensoranzeige. Die Vorlage setzt
`ACTUATORS_ENABLED=true`. Bei Bedarf lässt sie sich mit
`ACTUATORS_ENABLED=false` in `.env` abschalten. Nach einer Änderung an `.env` die
Container mit `docker compose up -d --build` neu starten. Die Regler sind ohne
Passwort bedienbar. Alle Ausgänge beginnen bei jedem Start mit 0 % und gehen in 5-%-Schritten
von 0 bis 100 %; zwischen 5 und 100 % steigt die reale Leistung linear:

| Gerät | GPIO | PWM | Real bei angezeigten 5 % | Anlauf aus 0 % |
| --- | ---: | ---: | ---: | --- |
| LED | 20 | 2000 Hz | 5 % | keiner |
| Lüfter | 21 | 5 Hz | 25 % | bei 5–50 %: 0,5 s mit 100 % |
| Pumpe | 16 | 5 Hz | 15 % | bei 5–30 %: 0,5 s mit 75 % |

Pins und Frequenzen stehen in `.env`. Ein harter
Prozessabbruch kann den letzten GPIO-Pegel bis zum Neustart stehen lassen.
Die Steuerung ist für ein vertrauenswürdiges lokales Netzwerk gedacht, da die
Webseite derzeit HTTP verwendet.

Vor dem Start dürfen keine früheren Dienste die Kamera oder die GPIO-Pins 16,
20 und 21 belegen. Sie sind kein Teil dieser Docker-Architektur.

InfluxDB ist unter `http://moos.local:8086` erreichbar.

Ein Sensorfehler verhindert die anderen Messungen nicht. Neben jeder erfolgreichen
Messung schreibt `sensors` `moos_sensor_health` mit `healthy=1`; bei einem
Lesefehler oder noch nicht bereite Werte `healthy=0`. Fehlende Messwerte werden nicht
als alte Werte wiederholt. Bei einer kurzen InfluxDB-Störung bleiben höchstens
2000 Punkte im Arbeitsspeicher; nach einem Container-Neustart ist dieser Puffer
verloren.

## InfluxDB-Schema

Measurement `moos_sensor`, Tags `side` (`left`/`right`/`tank`/`moss1`–`moss4`/`moss`)
und `sensor` (`sht45`/`bh1750`/`scd40`/`ultrasonic`/`aggregate`):

| Sensor | Felder |
| --- | --- |
| SHT45 | `temperature_c`, `humidity_pct` |
| BH1750 | `illuminance_lux` |
| SCD40 | `co2_ppm`, `temperature_c`, `humidity_pct` |
| Ultraschall | `water_level_cm`, `water_level_median_1m_cm`, `distance_cm` |
| Moos-Ultraschall 1–4 | `distance_cm`; nach Kalibrierung auch `height_cm`, `height_median_1m_cm` |
| Moos-Aggregat | `height_median_cm` bei mindestens drei gültigen Messstellen |

Zusätzlich zu den beidseitigen I²C-Werten und Wasserstandswerten werden die
Moos-Abstände und nach Kalibrierung die Höhen gespeichert.
Für den SCD40 werden auch seine Temperatur und Luftfeuchtigkeit gespeichert,
getrennt von den SHT45-Werten.

Technische Grundlagen: [SHT4x-Datenblatt](https://sensirion.com/media/documents/33FD6951/662A593A/HT_DS_Datasheet_SHT4x.pdf),
[SCD4x-Datenblatt](https://sensirion.com/media/documents/E0F04247/631EF271/CD_DS_SCD40_SCD41_Datasheet_D1.pdf),
[InfluxDB-Compose-Einrichtung](https://docs.influxdata.com/influxdb/v2/install/use-docker-compose/).
