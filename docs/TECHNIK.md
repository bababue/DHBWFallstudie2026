# Technische Hinweise

## Automatik

- Im AUTO-Modus prüft die Regelung laufend den Zielwasserstand und füllt bei Bedarf nach.
- Die Zielhöhe ist der Mittelwert der aktuellen 60-Sekunden-Mediane aller
  kalibrierten Moosmessstellen, abzüglich `wasser_unter_moosspitzen_cm`. Sie ist
  auf mindestens 0 cm und höchstens `max_fuellhoehe_cm - sicherheitsabstand_cm -
  pumpe_hysterese_cm` begrenzt.
- Mit `automatik.zielwasserstand_fest: true` wird stattdessen
  `zielwasserstand_cm` direkt als Ziel ab Tankboden verwendet, auch ohne
  kalibrierte oder verfügbare Moossensoren. Das Dashboard kennzeichnet diese
  Vorgabe und eine eventuelle Begrenzung durch die Sicherheitsgrenze.
  Wasserstandsmessung, Pumpensperre und 30-Sekunden-Startbestätigung bleiben nötig.
- Bei ausgeschalteter fester Vorgabe gilt die folgende Moosbestätigung.
- Der Zielwert wird erst übernommen, wenn alle kalibrierten Moossensoren
  aktuelle, als stabil markierte Messungen liefern und der gemeinsame Höhenwert
  drei Minuten lang höchstens 0,2 cm streut (Maximum minus Minimum).
  Übernommen wird der Median dieser bestätigten Höhenwerte.
- Änderungen bis 0,1 cm gegenüber der bestätigten Höhe werden ignoriert.
  Größere Änderungen müssen erneut drei Minuten bestätigt werden; bis dahin
  gilt der bisherige Zielwert. Ein Ausreißer startet diese Bestätigung neu.
- Bei fehlenden oder instabilen Moosmessungen wird der Zielwert ungültig und
  die Pumpe gesperrt. Erst nach erneuter Bestätigung wird nachgefüllt.
  Konfigurationsänderungen und ein Dashboard-Neustart erfordern ebenfalls
  eine neue Bestätigung. Unkalibrierte Messstellen werden nicht verwendet.
- Der aktuelle Wasserstand verwendet einen Medianfilter mit standardmäßig
  15 Rohmessungen (`wasserstand.filter_messungen`). Mindestens 80 % müssen
  innerhalb von `max_streuung_cm` (0,2 cm) um den Median liegen. Aus diesen
  Werten wird der Median gebildet. Bei fehlenden Echos oder instabilen Werten
  bleibt die automatische Nachfüllung gesperrt.
- Vor jedem Pumpenstart muss der gefilterte und der rohe Wasserstand 30 Sekunden
  durchgehend unter dem Ziel liegen; nach Erreichen des Ziels zusätzlich um die
  Hysterese darunter. Wellen oder Messausfälle setzen diese Wartezeit zurück.
  Beim Nachfüllen bleiben Zielabschaltung und Wasserstandssperre anhand des
  Rohwerts sofort wirksam. Der steigende Wasserstand wird nicht mehrere Minuten
  zurückgehalten.
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
| Moos-Ultraschall | `distance_cm`, `height_cm`, `height_median_1m_cm` |
| Aggregat | `height_median_cm` |

`side` ist `left`, `right`, `tank`, `moss1` bis `moss4` oder `moss`;
`sensor` ist `sht45`, `bh1750`, `scd40`, `ultrasonic` oder `aggregate`.
`moos_sensor_health` speichert je Messstelle und Sensor das Feld `healthy`.
