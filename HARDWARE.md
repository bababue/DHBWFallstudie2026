# Moos-Pi: Hardwareübersicht

Stand der Quellen: Übergabe vom 1. November 2026 und aktueller Projektstand. Alle GPIO-Angaben sind BCM-Nummern am Raspberry Pi 5 (`gpiochip0`). Die Angaben beschreiben den dokumentierten Aufbau; ausdrücklich ungeprüfte Punkte stehen am Ende. `config/config.json` ist maßgeblich für die vom Programm verwendeten Pins und Kalibrierwerte.

## Aufbau

Der dokumentierte physische Aufbau hat zwei Moos-Messstellen (links und rechts), einen Ultraschallsensor für den Wasserstand, Bewässerungspumpe, Lüfter, LED-Streifen, OLED-Anzeige, Taster und Pi-Kamera. Die Software unterstützt vier Moos-Sensoren; die Pins für Sensor 3 und 4 sind in der Konfiguration reserviert, ihr Einbau ist nicht dokumentiert. Jede seitliche I²C-Messstelle besitzt einen SHT45, einen GY-302/BH1750 und einen SCD40.

| Bauteil | Anzahl | Aufgabe / Anschluss |
| --- | ---: | --- |
| Raspberry Pi 5 | 1 | Zentrale Steuereinheit mit 40-poliger GPIO-Stiftleiste |
| SHT45 | 2 | **Primäre Messung von Temperatur und relativer Luftfeuchtigkeit**, je einer links und rechts |
| GY-302 mit BH1750 | 2 | Beleuchtungsstärke in Lux, je einer links und rechts |
| SCD40 | 2 | **Primäre Messung von CO₂** in ppm; seine Temperatur- und Feuchtewerte dienen nur als Backup zum SHT45, je einer links und rechts |
| Ultraschallsensor für Wasserstand | 1 | Trigger an GPIO 6, Echo an GPIO 13; dokumentierter Abstand vom Sensor zum Boden: **86,2 mm**; Sensormodell nicht angegeben. Den Betriebswert nach Kalibrierung in `config/config.json` prüfen. |
| Ultraschallsensoren für Mooshöhe | 2 | Je ein Trigger- und Echo-Pin gemäß Tabelle unten; Direkte Abstandsmessung ab Decke; Montagehöhen siehe unten |
| OLED, SSD1306 | 1 | 0,96 Zoll, 128 × 64 Pixel, am linken I²C-Bus; Anzeige um 180° gedreht |
| Taster | 1 | An GPIO 26 eingebaut; kurzer Druck wechselt den angezeigten Modus, Halten zeigt die Sensorübersicht |
| Pi-Kamera, Sensor IMX708 | 1 | Anschluss CAM/DISP1; in der Übergabe als Kamera 0 erkannt |
| Pumpe | 1 | 5 V, über IRLB8721-MOSFET an GPIO 16 geschaltet; derzeit softwareseitig deaktiviert |
| Lüfter | 1 | 5 V, dreipolig, über IRLB8721-MOSFET an GPIO 21 geschaltet; Tacholeitung nicht angeschlossen |
| LED-Streifen | 1 | 24 V, über IRLB8721-MOSFET an GPIO 20 geschaltet |

## Sensorbusse und Pinbelegung

Die beiden I²C-Busse verwenden GPIO-Paare, die keine Hardware-I²C-Paare des Pi sind. Sie werden deshalb über die GPIO-Leitungen betrieben. Auf beiden Seiten können die gleichen Sensoradressen verwendet werden, weil die Busse getrennt sind.

| Messstelle | SDA | SCL | I²C-Geräte und Adressen |
| --- | ---: | ---: | --- |
| Links | GPIO 15 | GPIO 14 | SHT45 `0x44`, GY-302/BH1750 `0x23`, SCD40 `0x62`, OLED/SSD1306 `0x3C` |
| Rechts | GPIO 23 | GPIO 24 | SHT45 `0x44`, GY-302/BH1750 `0x23`, SCD40 `0x62` |

| GPIO / Anschluss | Hardwarefunktion | Dokumentierter Stand |
| --- | --- | --- |
| 6 | Trigger des Wasserstand-Ultraschallsensors | Ausgang für den Messimpuls |
| 0 / 5 | Moos-Ultraschall 2: Trigger / Echo | Messstelle 2 |
| 9 / 11 | Moos-Ultraschall 1: Trigger / Echo | Messstelle 1 |
| 13 | Echo des Wasserstand-Ultraschallsensors | Eingang für das Echo-Signal |
| 14 / 15 | I²C links: SCL / SDA | Sensorbus links |
| 16 | Pumpe, MOSFET-Gate | 5-Hz-PWM vorgesehen |
| 20 | LED-Streifen, MOSFET-Gate | Im aktuellen Projekt 2.000-Hz-PWM vorgesehen; die PDF nennt 200 Hz |
| 21 | Lüfter, MOSFET-Gate | 5-Hz-PWM vorgesehen |
| 23 / 24 | I²C rechts: SDA / SCL | Getrennter Sensorbus |
| 26 | Eingebauter Taster | Eingang mit Pull-up, beim Drücken aktiv-low; Moduswahl und Sensorübersicht |
| 22 / 10 | Moos-Ultraschall 3: Trigger / Echo | Von der Software unterstützt, physischer Einbau nicht dokumentiert |
| 17 / 27 | Moos-Ultraschall 4: Trigger / Echo | Von der Software unterstützt, physischer Einbau nicht dokumentiert |
| CAM/DISP1 | Pi-Kamera IMX708 | Kamerasensor in der Übergabe erkannt |

## Konfigurations- und Kalibrierstatus

Die Software kennt vier Moos-Sensoren und misst echte Echos. Die derzeit
gemeinsame Montagehöhe (Sensorfläche–Tankboden) steht unter
`moos.montagehoehe_cm` in `config/config.json`. Der tatsächliche Einbau von
Sensor 3 und 4 ist in der Hardware-Übergabe nicht dokumentiert.

Der Sensor-Boden-Abstand des Wassersensors steht in `config/config.json`;
die Hardware-Übergabe nennt 8,62 cm. Den Wert am realen Einbau kalibrieren und
prüfen. Die maximale Füllhöhe muss kleiner als der Sensor-Boden-Abstand sein.

Bei den Sensorbussen wurde ein elektrisches Problem am linken Bus beobachtet: Mit hohem Bildinhalt auf dem OLED fielen Sensorantworten aus. Die dokumentierte Ansteuerung treibt SCL und eigene SDA-High-Bits aktiv; damit liefen beide Busse in einem 22-Sekunden-Test mit OLED fehlerfrei. Die vermutete Ursache sind Pull-ups oder ein Spannungseinbruch am OLED-Modul, **elektrisch bestätigt ist sie nicht**. Die 3,3-V-Verdrahtung der Busse muss geprüft sein, bevor diese Ansteuerung verwendet wird.

## Aktoren und Versorgung

Pumpe, Lüfter und LED-Streifen werden jeweils über einen IRLB8721-MOSFET vom Raspberry Pi angesteuert. Pumpe und Lüfter benötigen 5 V, der LED-Streifen 24 V. Konkrete Netzteilmodelle, Stromstärken, Sicherungen und die vollständige Masseverdrahtung sind in den Quellen nicht angegeben. Die GPIO-Ausgänge sind Steuersignale und keine Versorgung für die Lasten.

Der dokumentierte 5-Hz-Betrieb führt bei kleinen Stellwerten zu einzelnen Impulsen statt sicher gleichmäßigem Lauf. Ob die Pumpe dabei tatsächlich Wasser fördert und der Lüfter nach dem Anlaufen weiterläuft, wurde am echten Aufbau noch nicht bestätigt. Die Tacholeitung des Lüfters ist nicht angeschlossen; sie darf wegen möglicher 5 V nicht ungeprüft direkt an einen Pi-GPIO gelegt werden.

## Messstatus und offene Hardwarepunkte

- **SCD40:** Beide Sensoren wurden laut Übergabe per Forced Recalibration auf 430 ppm eingestellt, unter der Annahme frischer Luft am offenen Fenster. Dabei waren teils ungewöhnlich große Korrekturen nötig. Die CO₂-Werte und mögliche Drift sollten weiter beobachtet werden; die automatische Selbstkalibrierung war zum Übergabezeitpunkt aktiv.
- **Lastverhalten:** Wasserfluss und Lüfterlauf bei niedrigen Stellwerten sind offen.
- **Wasserstand-Ultraschallsensor:** Trigger GPIO 6, Echo GPIO 13. Den Sensor-Boden-Abstand am echten Einbau kalibrieren. Modell, Versorgung und Pegel der Echo-Leitung sind nicht dokumentiert; am Pi-Eingang höchstens 3,3 V sicherstellen.
- **Mooshöhen-Ultraschallsensoren:** Montagehöhen und Pinverfügbarkeit am echten Aufbau prüfen. Sensoren 3 und 4 sind softwareseitig vorgesehen, ihr physischer Einbau ist in der Übergabe nicht dokumentiert. Echo-Pegel und Pinverfügbarkeit (insbesondere GPIO 0 sowie GPIO 9–11) prüfen.
