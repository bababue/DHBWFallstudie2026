# Moos-Pi: Sensor-Ingest

Der `ingest`-Container liest auf dem Raspberry Pi 5 die drei I2C-Sensoren links
und rechts und schreibt ihre Messwerte in InfluxDB 2. Grafana zeigt die Daten an.
GPIO 12 wird nicht mehr mit PWM geschaltet.

## Konfiguration

Alle Pins (BCM-Nummern), I2C-Adressen, das Abtastintervall und die InfluxDB-
Zugangsdaten stehen in `.env`. Die Vorlage ist `.env.example`.

```sh
cp .env.example .env
```

Vor dem Start die drei Passwörter/Token in `.env` durch eigene lange Werte
ersetzen. Die Datei ist von Git ausgeschlossen. Bei einem bereits eingerichteten
InfluxDB-Datenverzeichnis ändern neue Initialisierungswerte den bestehenden
Benutzer oder Token nicht.

| Seite | SDA | SCL | Sensoren |
| --- | ---: | ---: | --- |
| links | GPIO 15 | GPIO 14 | SHT45 `0x44`, BH1750/GY-302 `0x23`, SCD40 `0x62` |
| rechts | GPIO 23 | GPIO 24 | SHT45 `0x44`, BH1750/GY-302 `0x23`, SCD40 `0x62` |

Die Busse sind Software-I2C. Der Code treibt eigene High-Bits aktiv, wie in der
Übergabe für diesen Aufbau beschrieben; das ist nur bei geprüfter 3,3-V-Verdrahtung
vertretbar. Der `ingest`-Container muss exklusiven Zugriff auf diese vier Pins
haben. Eine andere Steuerung, die dieselben I2C-Busse benutzt, darf nicht
gleichzeitig laufen.

Der B24_1 an GPIO 12 wird noch nicht gelesen: Seine Versorgungsspannung ist laut
Übergabe ungeprüft. `B24_1_ENABLED=true` wird deshalb bewusst abgewiesen.

## Start

Auf dem Pi mit Docker Compose:

```sh
docker compose up -d --build
docker compose logs -f ingest
```

InfluxDB: `http://moos.local:8086`; Grafana: `http://moos.local:3000`.
Grafana-Nutzer ist `admin`, Passwort steht in `.env`. Die InfluxDB-Datenquelle
`Moos InfluxDB` und das Dashboard `Moos-Kasten Sensoren` mit zwölf Mess- und
sechs Status-Panels werden beim Start eingerichtet. Das Dashboard verwendet den
Standard-Bucket `moos_sensors`; falls `INFLUXDB_BUCKET` geändert wird, die
Flux-Abfragen im Dashboard ebenfalls anpassen.

Ein Sensorfehler verhindert die anderen Messungen nicht. Neben jeder erfolgreichen
Messung schreibt der Ingest `moos_sensor_health` mit `healthy=1`; bei einem
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

## Grafana-Abfragen

Für jede Tabellenzeile ein **Time series**-Panel anlegen, die Datenquelle
`Moos InfluxDB` und Abfragesprache **Flux** wählen. In der Abfrage `<side>`,
`<sensor>` und `<field>` ersetzen. Für eine einzelne aktuelle Zahl denselben
Ausdruck in einem **Stat**-Panel verwenden und `Last (not null)` wählen.

```flux
from(bucket: "moos_sensors")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "moos_sensor")
  |> filter(fn: (r) => r.side == "<side>" and r.sensor == "<sensor>")
  |> filter(fn: (r) => r._field == "<field>")
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "mean")
```

| Panel-Titel | `<side>` | `<sensor>` | `<field>` | Einheit |
| --- | --- | --- | --- | --- |
| Temperatur links (SHT45) | `left` | `sht45` | `temperature_c` | °C |
| Feuchte links (SHT45) | `left` | `sht45` | `humidity_pct` | % |
| Licht links (BH1750) | `left` | `bh1750` | `illuminance_lux` | lx |
| CO₂ links (SCD40) | `left` | `scd40` | `co2_ppm` | ppm |
| Temperatur links (SCD40) | `left` | `scd40` | `temperature_c` | °C |
| Feuchte links (SCD40) | `left` | `scd40` | `humidity_pct` | % |
| Temperatur rechts (SHT45) | `right` | `sht45` | `temperature_c` | °C |
| Feuchte rechts (SHT45) | `right` | `sht45` | `humidity_pct` | % |
| Licht rechts (BH1750) | `right` | `bh1750` | `illuminance_lux` | lx |
| CO₂ rechts (SCD40) | `right` | `scd40` | `co2_ppm` | ppm |
| Temperatur rechts (SCD40) | `right` | `scd40` | `temperature_c` | °C |
| Feuchte rechts (SCD40) | `right` | `scd40` | `humidity_pct` | % |

Für Sensorzustände die Measurement auf `moos_sensor_health` und das Feld auf
`healthy` ändern. Hier keinen Mittelwert verwenden; `last` zeigt 1 für eine
erfolgreiche Messung und 0 für einen Fehler. Die erste SCD40-Messung ist erst
einige Sekunden nach dem Start verfügbar.

Technische Grundlagen: [SHT4x-Datenblatt](https://sensirion.com/media/documents/33FD6951/662A593A/HT_DS_Datasheet_SHT4x.pdf),
[SCD4x-Datenblatt](https://sensirion.com/media/documents/E0F04247/631EF271/CD_DS_SCD40_SCD41_Datasheet_D1.pdf),
[InfluxDB-Compose-Einrichtung](https://docs.influxdata.com/influxdb/v2/install/use-docker-compose/).
