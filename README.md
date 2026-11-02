# Moos-Pi: Sensoren

Der `sensors`-Container liest auf dem Raspberry Pi 5 die drei I2C-Sensoren links
und rechts und schreibt ihre Messwerte in InfluxDB 2. Das eigene Dashboard zeigt die Daten an.
GPIO 12 wird nicht mehr mit PWM geschaltet.

## Konfiguration

Alle Pins (BCM-Nummern), I2C-Adressen, das Abtastintervall und die InfluxDB-
Zugangsdaten stehen in `.env`. Die Vorlage ist `.env.example`.

`sensors` liest alle sechs Sensoren alle 6 Sekunden. Der SCD40 liefert im
normalen periodischen Modus etwa alle 5 Sekunden neue CO₂-Werte; 6 Sekunden
lassen dafür etwas Abstand und gelten auch als Mindestintervall dieser
gemeinsamen Abfrageschleife. Das Dashboard fragt InfluxDB jede Sekunde ab
und zeigt Werte nach 30 Sekunden ohne neues Sample nicht mehr als aktuell an.

```sh
cp .env.example .env
```

Vor dem Start die Platzhalter für Passwörter und Token in `.env` durch eigene
lange Werte ersetzen. Die Datei ist von Git ausgeschlossen. Bei einem bereits eingerichteten
InfluxDB-Datenverzeichnis ändern neue Initialisierungswerte den bestehenden
Benutzer oder Token nicht.

| Seite | SDA | SCL | Sensoren |
| --- | ---: | ---: | --- |
| links | GPIO 15 | GPIO 14 | SHT45 `0x44`, BH1750/GY-302 `0x23`, SCD40 `0x62` |
| rechts | GPIO 23 | GPIO 24 | SHT45 `0x44`, BH1750/GY-302 `0x23`, SCD40 `0x62` |

Die Busse sind Software-I2C. Der Code treibt eigene High-Bits aktiv, wie in der
Übergabe für diesen Aufbau beschrieben; das ist nur bei geprüfter 3,3-V-Verdrahtung
vertretbar. Der `sensors`-Container muss exklusiven Zugriff auf diese vier Pins
haben. Eine andere Steuerung, die dieselben I2C-Busse benutzt, darf nicht
gleichzeitig laufen.

Der B24_1 an GPIO 12 wird noch nicht gelesen: Seine Versorgungsspannung ist laut
Übergabe ungeprüft. `B24_1_ENABLED=true` wird deshalb bewusst abgewiesen.

## Start

Auf dem Pi mit Docker Compose:

```sh
# Einmalig bei einer Migration vom alten Aufbau:
sudo systemctl disable --now kamera-live moos-steuerung

docker compose up -d --build --remove-orphans
docker compose logs -f sensors
```

Der frühere Dienst `kamera-live` belegt Port 8000 und die Kamera;
`moos-steuerung` nutzt dieselben GPIO-Pins wie die Docker-Steuerung. Falls
Port 8000 weiterhin belegt ist, zeigt `sudo ss -ltnp '( sport = :8000 )'`
den Prozess. Die Abschaltung der alten Dienste ist nur einmalig nötig.
`--remove-orphans` entfernt beim Umstieg die früheren Container mit den
alten Dienstnamen. Das alte Grafana-Datenvolume kann danach einmalig mit
`docker volume rm dhbwfallstudie2026_grafana-data` gelöscht werden.

Die Container heißen `sensors`, `influxdb`, `dashboard` und `camera`.
Sensoren, Steuerung und Kamera laufen vollständig in Docker Compose.

Das einfache Dashboard ist unter `http://moos.local:8080` erreichbar. Es ordnet
die aktuellen Werte nach Temperatur, Luftfeuchte, Licht und CO₂ und zeigt
links und rechts nebeneinander, weiterhin ohne CSS. Der Browser
lädt die Seite einmal und erhält neue Werte über eine WebSocket-Verbindung.
Der Server prüft InfluxDB jede Sekunde und sendet Änderungen sofort an alle
verbundenen Browser. Messwerte, die älter als 30 Sekunden sind, erscheinen als
„kein aktueller Wert“. Die Zeiten lassen sich in `.env` über
`DASHBOARD_POLL_SECONDS` und `DASHBOARD_MAX_AGE_SECONDS` ändern. Bei einer
unterbrochenen Verbindung verbindet sich der Browser automatisch neu.

Auf derselben Seite erscheint der MJPEG-Livestream der Pi-Kamera. Der
`camera`-Container startet `rpicam-vid` erst, wenn ein Browser den Stream
öffnet, und gibt die Kamera nach dem letzten Zuschauer wieder frei. Der Stream
ist auch unter `http://moos.local:8000/stream.mjpg` erreichbar. `CAMERA_PORT`
in `.env` kann den Port ändern. Für den Kamerazugriff erhält der Container
Zugriff auf die Pi-Geräte; der `dashboard`-Container nutzt GPIO 16, 20 und 21.

Die Regler für Licht, Lüfter und Pumpe senden ihre Werte über dieselbe
WebSocket-Verbindung wie die Sensoranzeige. Die Steuerung ist zunächst mit
`ACTUATORS_ENABLED=false` abgeschaltet. Vor dem Einschalten die Freilaufdioden
an Lüfter und Pumpe und die Verdrahtung prüfen. Dann `ACTUATORS_ENABLED=true` und ein
langes `CONTROL_PASSWORD` in `.env` setzen und `docker compose up -d --build`
ausführen. Das Passwort wird beim Verstellen im Dashboard eingegeben. Alle
Ausgänge beginnen bei jedem Start mit 0 %. Die Regler gehen in 5-%-Schritten
von 0 bis 100 %; zwischen 5 und 100 % steigt die reale Leistung linear:

| Gerät | GPIO | PWM | Real bei angezeigten 5 % | Anlauf aus 0 % |
| --- | ---: | ---: | ---: | --- |
| LED | 20 | 200 Hz | 5 % | keiner |
| Lüfter | 21 | 5 Hz | 25 % | bei 5–50 %: 0,5 s mit 100 % |
| Pumpe | 16 | 5 Hz | 15 % | bei 5–30 %: 0,5 s mit 75 % |

Pins und Frequenzen stehen in `.env`. Ein harter
Prozessabbruch kann den letzten GPIO-Pegel bis zum Neustart stehen lassen.
Die Steuerung ist für ein vertrauenswürdiges lokales Netzwerk gedacht, da die
Webseite derzeit HTTP verwendet.

Vor dem Start dürfen keine früheren Dienste die Kamera, Port 8000 oder die
GPIO-Pins 16, 20 und 21 belegen. Sie sind kein Teil dieser Docker-Architektur.

InfluxDB ist unter `http://moos.local:8086` erreichbar.

Ein Sensorfehler verhindert die anderen Messungen nicht. Neben jeder erfolgreichen
Messung schreibt `sensors` `moos_sensor_health` mit `healthy=1`; bei einem
Lesefehler oder noch nicht bereite Werte `healthy=0`. Fehlende Messwerte werden nicht
als alte Werte wiederholt. Bei einer kurzen InfluxDB-Störung bleiben höchstens
2000 Punkte im Arbeitsspeicher; nach einem Container-Neustart ist dieser Puffer
verloren.

## InfluxDB-Schema

Measurement `moos_sensor`, Tags `side` (`left`/`right`) und `sensor`
(`sht45`/`bh1750`/`scd40`):

| Sensor | Felder |
| --- | --- |
| SHT45 | `temperature_c`, `humidity_pct` |
| BH1750 | `illuminance_lux` |
| SCD40 | `co2_ppm`, `temperature_c`, `humidity_pct` |

Das sind zwölf Zeitreihen: sechs Messgrößen pro Seite. Für den SCD40 werden auch
seine Temperatur und Luftfeuchtigkeit gespeichert, getrennt von den SHT45-Werten.

Technische Grundlagen: [SHT4x-Datenblatt](https://sensirion.com/media/documents/33FD6951/662A593A/HT_DS_Datasheet_SHT4x.pdf),
[SCD4x-Datenblatt](https://sensirion.com/media/documents/E0F04247/631EF271/CD_DS_SCD40_SCD41_Datasheet_D1.pdf),
[InfluxDB-Compose-Einrichtung](https://docs.influxdata.com/influxdb/v2/install/use-docker-compose/).
