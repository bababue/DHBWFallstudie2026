# Messung und Bewässerung

## Messwerte

Alle Ultraschallsensoren liefern `distance_cm` direkt ab ihrer Sensorfläche.
Bei den Moossensoren ist das der Abstand ab Decke zur Moosoberfläche.
Der gemeinsame Filter in `src/measurements.py` verwendet 15 Messungen:
Mindestens 80 % müssen innerhalb von ±0,2 cm (Wasser) bzw. ±0,3 cm (Moos)
um den Median liegen. Aus diesen Werten wird der Median gebildet.
Bei fehlenden Echos oder einer Messpause über 12 Sekunden beginnt der Filter neu.
Rohwert, gefilterter Wert und Gültigkeit werden von Anzeige, Datenbank und
Regelung gemeinsam verwendet. Fehlgeschlagene Messungen ersetzen alte Werte.

Die Montagehöhe ist der Abstand Sensorfläche–Tankboden. Für Sensor 1 und 2
wurden 12,94 cm und 12,059 cm aus den bisherigen Kalibrierungen übernommen.
Sensoren 3 und 4 messen ebenfalls Abstände, werden aber erst mit eingetragener
`montagehoehe_cm` zur Bewässerung herangezogen.

## Ziel und Pumpenfreigabe

```text
Ziel = Mittelwert(Montagehöhe − gefilterter Moosabstand) − 2,5 cm
```

Alle zur Regelung eingetragenen Moossensoren müssen stabile, höchstens
12 Sekunden alte Messungen liefern. Zielwerte werden auf 0 bis
`max_fuellhoehe_cm − pumpe_hysterese_cm` begrenzt, aktuell 0 bis 6,8 cm.
Ein fester Zielwert und eine zusätzliche Mooshöhen-Aggregation entfallen.

Nach jedem Eintritt in AUTO muss „Automatische Pumpe freigeben“ im Dashboard
angeschaltet und im Dialog bestätigt werden. Die Freigabe wird nicht gespeichert.
Neue Modussitzung, Sensor-/Dashboard-/Pi-Neustart, abgelaufener Modus-Snapshot
oder Konfigurationsänderung entziehen sie. Eine Bestätigung aus einem zuvor
geöffneten Dialog wird dann abgewiesen. Ausschalten ist ohne Dialog möglich.
Ein kurzzeitig ungültiger Abstand sperrt das Nachfüllen innerhalb der Sitzung;
nach der Erholung muss die Einschaltbedingung erneut 30 Sekunden bestehen.

Die Regelung kennt drei Zustände:

- **Gesperrt:** keine Freigabe, ungültige Messwerte oder Sicherheitsgrenze erreicht.
- **Warten:** Wasser im Zielbereich oder niedriger Stand noch nicht bestätigt.
- **Nachfüllen:** gefilterter Wasserstand seit 30 Sekunden unter Ziel minus 0,2 cm.
  Die Pumpe läuft mit 25 % bis zum gefilterten Zielwasserstand.

Eine einzelne Welle am normalen Zielwert beendet das Nachfüllen nicht.
Der rohe Wasserstand ab **7,0 cm** schaltet die Pumpe dagegen sofort ab,
auch in MANUAL. Die Grenze ist jetzt direkt `wasserstand.max_fuellhoehe_cm`;
der bisherige Sicherheitsabstand wurde bereits eingerechnet.
Fehlende Wasser-Echos oder Wasserwerte älter als 3 Sekunden sperren ebenfalls.
Der gemeinsame Sensor-Snapshot und der Modus dürfen höchstens 5 Sekunden alt sein.
Die Pumpensteuerung besitzt den Zustand; HTTP-Abfragen lesen nur seinen Snapshot.
Alle Filter-, Alters- und Zeitgrenzen stehen zentral in `src/measurements.py`.

## Speicherung und Anzeige

`moos_sensor` hat die Tags `side` (`left`, `right`, `tank`, `moss1` bis `moss4`)
und `sensor` (`sht45`, `bh1750`, `scd40`, `ultrasonic`).
Ultraschallfelder: `distance_cm`, `distance_filtered_cm`, `measurement_stable`;
beim Wasser zusätzlich `water_level_cm` und `max_level_reached`.
Die bisherigen Papier-Bezugsabstände und Mooshöhenfelder werden nicht mehr erzeugt.
Historische Daten bleiben erhalten. `moos_sensor_health.healthy` dokumentiert
Sensorantworten; die Verwendbarkeit gefilterter Abstände bestimmt `measurement_stable`.

Das Dashboard zeigt Deckenabstände je Moossensor, Wasserstand, Ziel und Pumpenzustand.
Der Wassergraph enthält Messhistorie und eine Linie für das aktuelle Ziel.
OLED und Debug-Tabelle verwenden dieselben gefilterten Abstände.
