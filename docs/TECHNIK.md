# Messung und Bewässerung

## Messwerte

Alle Ultraschallsensoren liefern `distance_cm` direkt ab ihrer Sensorfläche.
Bei den Moossensoren ist das der Abstand ab Decke zur Moosoberfläche.
Der gemeinsame Filter verwendet die Werte unter `ultraschall_glaettung` in
`config/config.json`: standardmäßig 60 Messungen. Nur Werte innerhalb von
±0,2 cm (Wasser) bzw. ±0,3 cm (Moos) um den Median dieser 60 Messungen
fließen in den geglätteten Abstand ein. Ihr Anteil wird in Prozent angezeigt.
Liegt kein Wert innerhalb der Streuung, gibt es keinen geglätteten Abstand.
Bei fehlenden Echos oder einer Messpause über `max_messpause_s` beginnt der Filter neu.
Die Pause ist höchstens 12 Sekunden einstellbar.
Rohwert, gefilterter Wert und Gültigkeit werden von Anzeige, Datenbank und
Regelung gemeinsam verwendet. Fehlgeschlagene Messungen ersetzen alte Werte.

Die gemeinsame Montagehöhe ist der Abstand Sensorfläche–Tankboden und steht
unter `moos.montagehoehe_cm` in `config/config.json`. Die Pins der vier
Sensoren stehen unter `moos.sensoren`.

## Pumpe

Die Pumpe ist derzeit vollständig deaktiviert. Der Pumpenausgang wird beim Start
auf 0 gesetzt und jeder Einschaltbefehl wird in AUTO und MANUAL zurückgewiesen.

## Speicherung und Anzeige

`moos_sensor` hat die Tags `side` (`left`, `right`, `tank`, `moss1` bis `moss4`)
und `sensor` (`sht45`, `bh1750`, `scd40`, `ultrasonic`).
Ultraschallfelder: `distance_cm`, `distance_filtered_cm`,
`distance_inlier_percent`, `measurement_stable`;
beim Wasser zusätzlich `water_level_cm` und `max_level_reached`.
Die bisherigen Papier-Bezugsabstände und Mooshöhenfelder werden nicht mehr erzeugt.
Historische Daten bleiben erhalten. `moos_sensor_health.healthy` dokumentiert
Sensorantworten; die Verwendbarkeit gefilterter Abstände bestimmt `measurement_stable`.

Das Dashboard zeigt die berechnete Wasserhöhe und den Median der Mooshöhen. Pro
Zeitfenster wird der letzte geglättete Abstand je verfügbarem Moossensor
verwendet; fehlende Messungen werden nicht als Werte erfunden. Die Debug-Tabelle
zeigt zusätzlich Rohabstände, geglättete Abstände, ihren Inlier-Anteil, die
einzelnen berechneten Höhen und deren aktuellen Median.
