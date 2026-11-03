# Technische Hinweise

## Automatik

- Im AUTO-Modus prüft die Regelung laufend den Zielwasserstand und füllt bei Bedarf nach.
- Die Zielhöhe ist der Mittelwert der aktuellen 60-Sekunden-Mediane aller
  kalibrierten Moosmessstellen, abzüglich `wasser_unter_moosspitzen_cm`. Sie ist
  auf mindestens 0 cm und höchstens `max_fuellhoehe_cm - sicherheitsabstand_cm -
  pumpe_hysterese_cm` begrenzt.
- Ein Pumpvorgang endet am Ziel. Bei erreichtem Ziel stoppt sie; bei erneutem Absinken unter die Hysterese
  füllt sie wieder nach. Fehlen sichere Wasser- oder Mooswerte,
  endet ein laufender Vorgang. Die Wasserstands-Sperre gilt in AUTO und MANUAL.
- In AUTO dimmt das Licht oberhalb des Temperaturziels. Die wärmere Seite zählt;
  SCD40 ersetzt dort einen fehlenden SHT45. Bei fehlender Seite gilt Licht aus
  und Lüfter 100 %. Beim konfigurierten Temperaturmaximum greift derselbe Schutz
  und bleibt aktiv, bis beide Seiten unter Maximum minus 1 °C liegen.

## InfluxDB

`moos_sensor` verwendet die Tags `side` und `sensor`. Häufige Felder:

| Messung | Felder |
| --- | --- |
| SHT45 | `temperature_c`, `humidity_pct` |
| BH1750 | `illuminance_lux` |
| SCD40 | `co2_ppm`, `temperature_c`, `humidity_pct` |
| Wasser-Ultraschall | `distance_cm`, `distance_filtered_cm`, `water_level_cm`, `measurement_stable` |
| Moos-Ultraschall | `distance_cm`, `height_cm`, `height_median_1m_cm`, `demo_data` |
| Aggregat | `height_median_cm` |

`side` ist `left`, `right`, `tank`, `moss1` bis `moss4` oder `moss`;
`sensor` ist `sht45`, `bh1750`, `scd40`, `ultrasonic` oder `aggregate`.
`moos_sensor_health` speichert je Messstelle und Sensor das Feld `healthy`.
