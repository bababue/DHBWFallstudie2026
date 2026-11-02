# Moos-Pi: Sensoren

Der `sensors`-Container liest auf dem Raspberry Pi 5 die drei I2C-Sensoren links
und rechts sowie fünf Ultraschallsensoren für Wasserstand und Mooshöhe. Er schreibt
ihre Messwerte in InfluxDB 2; das Dashboard zeigt sie an.

## Konfiguration

Hardwareparameter und Messintervalle stehen in der versionierten Datei
`config/config.json`. Änderungen können direkt in der Datei vorgenommen werden;
die Software prüft Struktur, Wertebereiche und doppelt vergebene GPIOs. Sensoränderungen
starten den Sensorcontainer automatisch neu (der angezeigte Modus beginnt wieder
in AUTO). `null` bei einem Moos-Bezugsabstand bedeutet „noch nicht kalibriert“.
I²C-Adressen sind dezimale Zahlen: 68 = 0x44, 35 = 0x23, 98 = 0x62.

`.env` enthält die InfluxDB-Verbindung, Zugangsdaten und das GPIO-Gerät für
Compose. Die Hardwareparameter werden aus `config/config.json` gelesen.

Lokale Änderungen an der versionierten Datei können den automatischen Deploy
verhindern und müssen vor einem Git-Update übernommen oder gesichert werden.

`sensors` liest SHT45, BH1750 und den Wasserstandsensor unabhängig voneinander
etwa jede Sekunde. Beim SCD40 prüft es alle 0,5 Sekunden, ob ein neuer CO₂-Wert
bereitliegt; der Sensor selbst erzeugt nur etwa alle 5 Sekunden einen neuen Wert.
Zwischen diesen Messungen wird kein alter CO₂-Wert erneut gespeichert.
Datenbank-Schreibvorgänge laufen getrennt von den GPIO-Abfragen. Das Dashboard
fragt aktuelle Messwerte alle zwei Sekunden ab und zeigt Werte nach 12 Sekunden ohne neues
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
nicht.

| Seite | SDA | SCL | Sensoren |
| --- | ---: | ---: | --- |
| links | GPIO 15 | GPIO 14 | SHT45 `0x44`, BH1750/GY-302 `0x23`, SCD40 `0x62` |
| rechts | GPIO 23 | GPIO 24 | SHT45 `0x44`, BH1750/GY-302 `0x23`, SCD40 `0x62` |

Der Wasserstandsensor nutzt Trigger GPIO 6 und Echo GPIO 13. Aus dem gemessenen
Abstand zur Wasseroberfläche und dem Sensor-Boden-Abstand von 8,62 cm berechnet
die Software die Wassertiefe in cm. Der Rohabstand bleibt unverändert sichtbar.
Echozeiten werden über GPIO-Flanken mit Nanosekunden-Zeitstempeln erfasst.
Die Füllhöhe verwendet einen kurzen Medianfilter: `filter_messungen` bestimmt
die Anzahl (Standard 5); mindestens eine Mehrheit muss innerhalb von
`max_streuung_cm` um den Median liegen. Erst dann wird `water_level_cm` geschrieben.
Ein fehlendes Echo oder eine Messpause über 12 Sekunden leert den Filter.
`measurement_stable` kennzeichnet den Messzustand.

`wasserstand.max_fuellhoehe_cm` ist die maximale erlaubte Füllhöhe. `null`
bedeutet noch nicht festgelegt. `max_level_reached` meldet eine Überschreitung
bereits beim einzelnen Rohwert und zusätzlich beim gefilterten Wert.
Diese Meldung schaltet bislang keine Pumpe; eine unabhängige Hardwareabschaltung
(z. B. Schwimmerschalter) muss separat eingebaut werden. Ein dauerhaftes Hindernis
im Schallweg kann auch einen Medianfilter täuschen.

Kalibrierung im leeren Behälter, mit ruhiger Oberfläche und freiem Schallweg:

```sh
python3 scripts/calibrate_water.py
```

Das Skript fragt zuerst, ob der Tank leer ist. Bei angegebener Wassertiefe muss
diese stattdessen bestätigt werden. Danach stoppt es einen laufenden Sensorcontainer vorübergehend, misst 200 Echos
im Container und startet ihn danach wieder. Bei ausreichender Messqualität fragt
es nach der Messung, ob das Ergebnis gespeichert werden soll. Bei bekannter
Wassertiefe kann `--water-height 1.5` angegeben werden.
Die Kalibrierung ersetzt nicht die Prüfung des Mindestabstands laut Sensordatenblatt.
Die Echo-Leitung muss am Pi-Eingang auf höchstens 3,3 V begrenzt sein.

Vier zusätzliche Ultraschallsensoren messen den Abstand zur Moosoberfläche:
Ihre Echozeiten werden wie beim Wassersensor über GPIO-Flanken mit Zeitstempeln
erfasst. Das gilt auch für die Kalibrierung der Moossensoren.

Für synthetische Moosdaten bei jedem gewünschten Sensor `moos_1.demo` bis
`moos_4.demo` in `config/config.json` auf `true` setzen. Die Werte sind
normalverteilt um den jeweiligen `demo_abstand_cm`. Ist dieser `null`, liefert
der Demo-Sensor keine Messwerte. Für kalibrierte Sensoren liegt der anfängliche
Demo-Abstand 1 cm über dem Bezugsabstand. Echte Messwerte oberhalb der
Deckelgrenze ersetzen den Demowert und dienen der Deckelerkennung. Bei `demo: false` wird der echte Sensor genutzt.
Die Standardabweichung wird laufend aus den gültigen Rohabständen des
Wassersensors der letzten 60 Sekunden geschätzt. Mindestens fünf Messwerte sind
nötig; ohne diese werden keine Demowerte erzeugt. Auch tatsächliche Änderungen
des Wasserstands beeinflussen diese Schätzung. Die Daten werden in InfluxDB
gespeichert und tragen dort das Feld `demo_data=true`; echte Moosmessungen
erhalten `false`. Der Sensorcontainer übernimmt Konfigurationsänderungen durch
Neustart.

Für die Kalibrierung beider SCD40 den Kasten geöffnet draußen aufstellen und
`python3 scripts/calibrate_co2.py` auf dem Pi ausführen. Das Skript fragt nach
dem Referenzwert (430 ppm als Schätzung), misst fünf Minuten und kalibriert nur
bei stabilen Messwerten nach Bestätigung. Ein kalibriertes Referenzgerät liefert
einen genaueren Wert. Die Kalibrierung wird im Sensor gespeichert; die automatische
Selbstkalibrierung wird nicht verändert. Der Sensorcontainer wird währenddessen
angehalten und danach wieder gestartet, sofern er zuvor lief.

Zur Kalibrierung aller vier Sensoren `python3 scripts/calibrate_moss.py`
ausführen und den Kalibrierungszettel auf die Halterung legen. Nach Enter misst
das Skript jeden Sensor 200-mal mit 0,1 Sekunden Pause und fragt, ob stabile
Bezugsabstände in `config/config.json` gespeichert werden sollen. Nicht angeschlossene oder instabile Sensoren behalten ihren
bisherigen Wert. Der Sensorcontainer wird währenddessen angehalten und danach
wieder gestartet, falls er zuvor lief.

| Sensor | Trigger | Echo | Kalibrierwert in `config/config.json` |
| --- | ---: | ---: | --- |
| Moos 1 | GPIO 9 | GPIO 11 | `moos_1.bezugsabstand_cm` |
| Moos 2 | GPIO 0 | GPIO 5 | `moos_2.bezugsabstand_cm` |
| Moos 3 | GPIO 22 | GPIO 10 | `moos_3.bezugsabstand_cm` |
| Moos 4 | GPIO 17 | GPIO 27 | `moos_4.bezugsabstand_cm` |

Jeder Kalibrierwert ist der Abstand vom Sensor zur moosfreien Bezugsfläche in cm.
Ohne ihn wird nur der Rohabstand angezeigt. Mit ihm berechnet die Software die
Mooshöhe je Messstelle. Der Rohabstand zeigt jeweils genau eine aktuelle Messung;
die Sensoren starten um zwei Sekunden versetzt und messen jeweils alle vier Sekunden.
Für den gemeinsamen Wert nimmt die Software den Median der 60-Sekunden-Mediane
beider gültigen, kalibrierten Messstellen. Bei zwei Werten entspricht das ihrem
Mittelwert; einzelne Ausreißer lassen sich damit nur zeitlich, nicht zwischen
den Messstellen herausfiltern. Unterschiedliche Montagehöhen werden über die
einzelnen Kalibrierwerte berücksichtigt.

Die Busse sind Software-I2C. Der Code treibt eigene High-Bits aktiv, wie in der
Übergabe für diesen Aufbau beschrieben; das ist nur bei geprüfter 3,3-V-Verdrahtung
vertretbar. Der `sensors`-Container muss exklusiven Zugriff auf die vier I2C-Pins
und alle sechs Ultraschall-Pins haben. Eine andere Steuerung, die dieselben GPIOs benutzt, darf nicht
gleichzeitig laufen.

## OLED-Anzeige

Das SSD1306-OLED (128 × 64, Adresse `0x3C`) hängt am linken Sensorbus und ist um
180° gedreht. `sensors` rendert die Anzeige direkt aus seinen Messwerten und
greift als einziger Container auf GPIO 14 und 15 zu.

Das Display zeigt normalerweise den aktuellen Modus `AUTO` oder `MAINTENANCE`.
Ein kurzer Druck auf den Taster an GPIO 26 schaltet zwischen beiden um. Während der
Taster mindestens 0,6 Sekunden gehalten wird, zeigt das Display die
Sensorübersicht. Beim Loslassen erscheint wieder der Modus, ohne weiterzuschalten.
Der Taster wird mit Pull-up gelesen und ist beim Drücken aktiv-low. Nach jedem
Neustart beginnt die Anzeige in `AUTO`. Im Modus `MAINTENANCE` laufen die
Sensoren weiter und ihre aktuellen Werte werden angezeigt, aber nicht in
InfluxDB gespeichert. Im Dashboard sind die Graphen währenddessen ausgeblendet.
Im AUTO-Modus setzt die automatische Steuerung Lüfter, Pumpe und Licht derzeit
auf 0 %. Beim Verlassen von MAINTENANCE werden diese Sollwerte wieder übernommen.
Im Maintenance-Modus lassen sich Lüfter, Pumpe und Licht im Dashboard einstellen.
Die Regler zeigen den zuletzt gesetzten Stellwert; beim Start der Dashboard-Steuerung
werden die Ausgänge auf 0 gesetzt. Die GPIOs und PWM-Frequenzen stehen unter
`aktoren` in der Konfiguration. Nach einer Änderung den Dashboard-Container neu starten.

Die Sensorübersicht zeigt links und rechts Temperatur und Luftfeuchte vom SHT45,
CO₂ vom SCD40 sowie Helligkeit vom BH1750. Falls ein SHT45-Wert fehlt, dient
der entsprechende SCD40-Wert als Backup.

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

Der systemd-Timer `moos-deploy.timer` prüft `origin/master` alle 10 Sekunden
auf Änderungen. Nach einer Änderung an der Timer-Datei muss die installierte
Version auf dem Pi einmal aktualisiert werden:

```sh
sudo install -m 644 deploy/moos-deploy.timer /etc/systemd/system/moos-deploy.timer
sudo systemctl daemon-reload
sudo systemctl enable --now moos-deploy.timer
sudo systemctl restart moos-deploy.timer
```

Die Container heißen `sensors`, `influxdb`, `dashboard` und `camera`.
Sensoren, OLED, Steuerung und Kamera laufen vollständig in Docker Compose.

Das Dashboard ist unter `http://moos.local:8080` erreichbar. Es zeigt den
aktuellen Modus des OLED-Tasters und den Kamerastream. Der Modus wird über ein
gemeinsames Volume zwischen Sensorprozess und Dashboard ausgetauscht. Fällt der
Sensorprozess aus, meldet das Dashboard den Modus als nicht verfügbar.
Der Debug-Modus blendet eine Tabelle mit den letzten Temperatur- und
Luftfeuchtigkeitswerten von SHT45 und SCD40 links und rechts ein. Die bereits
in °C und Prozent gespeicherten Einzelwerte werden unverändert angezeigt;
Messwerte, die älter als 12 Sekunden sind, erscheinen nicht mehr als aktuell.

Die Temperaturkachel zeigt den Mittelwert der aktuellen SHT45-Messungen links
und rechts. Fehlt ein SHT45, wird der SCD40 derselben Seite als gekennzeichnetes
Backup verwendet; bei nur einer verfügbaren Seite wird diese gekennzeichnet.
Die Kachel zeigt die Werte links und rechts sowie die relative Differenz
`(rechts − links) / links × 100` in Prozent. Bei links = 0 erscheint „–“;
ein SCD40-Ersatz ist mit „(fallback)“ gekennzeichnet. Der aktuelle Wert wird
alle zwei Sekunden aktualisiert. Luftfeuchtigkeit steht als gleichartige Kachel
neben Temperatur und verwendet ebenfalls SHT45 mit SCD40 als Backup.
Beide Verläufe bieten 10 Minuten, 1 Stunde, 24 Stunden, 7 Tage
und 30 Tage; sie werden alle 30 Sekunden aktualisiert. Für 10 Minuten wird je
2-Sekunden-Fenster der letzte Wert verwendet. Für eine Stunde wird je
10-Sekunden-Fenster der letzte Wert verwendet, für längere Zeiträume jeweils
das Mittel pro Sensor und Zeitfenster (1, 5 oder 30 Minuten). Fehlende Fenster
erscheinen als Lücke. Die ursprünglichen Messwerte bleiben in InfluxDB erhalten.

Der `camera`-Container startet `rpicam-vid`, wenn ein Browser den Stream öffnet,
und gibt die Kamera nach dem letzten Zuschauer wieder frei. Der Stream ist auch
unter `http://moos.local:8080/camera/stream.mjpg` erreichbar.

InfluxDB ist unter `http://moos.local:8086` erreichbar.

Ein Sensorfehler verhindert die anderen Messungen nicht. Neben jeder erfolgreichen
Messung schreibt `sensors` `moos_sensor_health` mit `healthy=1`; bei einem
Lesefehler oder noch nicht bereite Werte `healthy=0`. Fehlende Messwerte werden nicht
als alte Werte wiederholt. Bei einer kurzen InfluxDB-Störung bleiben höchstens
2000 Punkte im Arbeitsspeicher; nach einem Container-Neustart ist dieser Puffer
verloren.

## InfluxDB-Schema

Measurement `moos_sensor`, Tags `side` (`left`/`right`/`tank`/`moss1`/`moss2`/`moss`)
und `sensor` (`sht45`/`bh1750`/`scd40`/`ultrasonic`/`aggregate`):

| Sensor | Felder |
| --- | --- |
| SHT45 | `temperature_c`, `humidity_pct` |
| BH1750 | `illuminance_lux` |
| SCD40 | `co2_ppm`, `temperature_c`, `humidity_pct` |
| Ultraschall | `distance_cm`, `distance_filtered_cm`, `water_level_cm`, `measurement_stable`, `max_level_configured`, `max_level_reached` (wenn Grenze gesetzt) |
| Moos-Ultraschall 1–2 | `distance_cm`; nach Kalibrierung auch `height_cm`, `height_median_1m_cm` |
| Moos-Aggregat | `height_median_cm` bei zwei gültigen Messstellen |

Zusätzlich zu den beidseitigen I²C-Werten und Wasserstandswerten werden die
Moos-Abstände und nach Kalibrierung die Höhen gespeichert.
Für den SCD40 werden auch seine Temperatur und Luftfeuchtigkeit gespeichert,
getrennt von den SHT45-Werten.

Technische Grundlagen: [SHT4x-Datenblatt](https://sensirion.com/media/documents/33FD6951/662A593A/HT_DS_Datasheet_SHT4x.pdf),
[SCD4x-Datenblatt](https://sensirion.com/media/documents/E0F04247/631EF271/CD_DS_SCD40_SCD41_Datasheet_D1.pdf),
[InfluxDB-Compose-Einrichtung](https://docs.influxdata.com/influxdb/v2/install/use-docker-compose/).

Die Deckelerkennung verwendet `deckel.offen_abstand_cm` (Standard: 12 cm).
Drei gültige Messungen eines Moossensors oberhalb der Grenze aktivieren
MAINTENANCE und sperren den Taster für Moduswechsel. Erst drei gültige
Messungen auf oder unter der Grenze von jedem zuvor geöffnet erkannten Sensor
schalten zurück auf AUTO. Fehlende Echos bestätigen keinen Zustandswechsel.
Während MAINTENANCE laufen alle Messungen weiter, ohne in InfluxDB gespeichert
zu werden. Die Deckelprüfung verwendet auch im Demo-Modus echte Sensorwerte.
