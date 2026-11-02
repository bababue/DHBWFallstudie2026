# Moos-Pi: Hardwareübersicht

Stand der Quellen: Übergabe vom 1. November 2026 und aktueller Projektstand. Alle GPIO-Angaben sind BCM-Nummern am Raspberry Pi 5 (`gpiochip0`). Die Angaben beschreiben den dokumentierten Aufbau; ausdrücklich ungeprüfte Punkte stehen am Ende.

## Aufbau

Der Raspberry Pi 5 betreut einen Moos-Kasten mit zwei Messstellen (links und rechts), einem Ultraschallsensor für den Wasserstand, Bewässerungspumpe, Lüfter, LED-Streifen, OLED-Anzeige, Taster und Pi-Kamera. Jede Messstelle besitzt einen SHT45, einen GY-302/BH1750 und einen SCD40.

| Bauteil | Anzahl | Aufgabe / Anschluss |
| --- | ---: | --- |
| Raspberry Pi 5 | 1 | Zentrale Steuereinheit mit 40-poliger GPIO-Stiftleiste |
| SHT45 | 2 | **Primäre Messung von Temperatur und relativer Luftfeuchtigkeit**, je einer links und rechts |
| GY-302 mit BH1750 | 2 | Beleuchtungsstärke in Lux, je einer links und rechts |
| SCD40 | 2 | **Primäre Messung von CO₂** in ppm; seine Temperatur- und Feuchtewerte dienen nur als Backup zum SHT45, je einer links und rechts |
| Ultraschallsensor für Wasserstand | 1 | Trigger an GPIO 6, Echo an GPIO 13; Abstand vom Sensor zum Boden: **86,2 mm**; Sensormodell nicht angegeben |
| OLED, SSD1306 | 1 | 0,96 Zoll, 128 × 64 Pixel, am linken I²C-Bus; in der Übergabe um 180° gedreht angesteuert |
| Taster | 1 | GPIO 26, gegen GND mit internem Pull-up vorgesehen |
| Pi-Kamera, Sensor IMX708 | 1 | Anschluss CAM/DISP1; in der Übergabe als Kamera 0 erkannt |
| Pumpe | 1 | 5 V, über IRLB8721-MOSFET an GPIO 16 geschaltet |
| Lüfter | 1 | 5 V, dreipolig, über IRLB8721-MOSFET an GPIO 21 geschaltet; Tacholeitung nicht angeschlossen |
| LED-Streifen | 1 | 24 V, über IRLB8721-MOSFET an GPIO 20 geschaltet |
| ALLNET B24_1 | 1 | Temperatur-/Feuchtemodul an GPIO 12; testweise nach DHT11-Protokoll gelesen, im aktuellen Aufbau nicht als reguläre Messquelle genutzt |

## Sensorbusse und Pinbelegung

Die beiden I²C-Busse verwenden GPIO-Paare, die keine Hardware-I²C-Paare des Pi sind. Sie werden deshalb über die GPIO-Leitungen betrieben. Auf beiden Seiten können die gleichen Sensoradressen verwendet werden, weil die Busse getrennt sind.

| Messstelle | SDA | SCL | I²C-Geräte und Adressen |
| --- | ---: | ---: | --- |
| Links | GPIO 15 | GPIO 14 | SHT45 `0x44`, GY-302/BH1750 `0x23`, SCD40 `0x62`, OLED/SSD1306 `0x3C` |
| Rechts | GPIO 23 | GPIO 24 | SHT45 `0x44`, GY-302/BH1750 `0x23`, SCD40 `0x62` |

| GPIO / Anschluss | Hardwarefunktion | Dokumentierter Stand |
| --- | --- | --- |
| 6 | Trigger des Wasserstand-Ultraschallsensors | Ausgang für den Messimpuls |
| 12 | ALLNET B24_1 | Versorgungsspannung des Moduls ungeprüft; kein PWM-Ausgang mehr |
| 13 | Echo des Wasserstand-Ultraschallsensors | Eingang für das Echo-Signal |
| 14 / 15 | I²C links: SCL / SDA | Sensorbus links |
| 16 | Pumpe, MOSFET-Gate | 5-Hz-PWM vorgesehen |
| 20 | LED-Streifen, MOSFET-Gate | Im aktuellen Projekt 2.000-Hz-PWM vorgesehen; die PDF nennt 200 Hz |
| 21 | Lüfter, MOSFET-Gate | 5-Hz-PWM vorgesehen |
| 23 / 24 | I²C rechts: SDA / SCL | Getrennter Sensorbus |
| 26 | Taster | Interner Pull-up; Schließen gegen GND angenommen |
| CAM/DISP1 | Pi-Kamera IMX708 | Kamerasensor in der Übergabe erkannt |

Bei den Sensorbussen wurde ein elektrisches Problem am linken Bus beobachtet: Mit hohem Bildinhalt auf dem OLED fielen Sensorantworten aus. Die dokumentierte Ansteuerung treibt SCL und eigene SDA-High-Bits aktiv; damit liefen beide Busse in einem 22-Sekunden-Test mit OLED fehlerfrei. Die vermutete Ursache sind Pull-ups oder ein Spannungseinbruch am OLED-Modul, **elektrisch bestätigt ist sie nicht**. Die 3,3-V-Verdrahtung der Busse muss geprüft sein, bevor diese Ansteuerung verwendet wird.

## Aktoren und Versorgung

Pumpe, Lüfter und LED-Streifen werden jeweils über einen IRLB8721-MOSFET vom Raspberry Pi angesteuert. Pumpe und Lüfter benötigen 5 V, der LED-Streifen 24 V. Konkrete Netzteilmodelle, Stromstärken, Sicherungen und die vollständige Masseverdrahtung sind in den Quellen nicht angegeben. Die GPIO-Ausgänge sind Steuersignale und keine Versorgung für die Lasten.

Für Pumpe und Lüfter sind Freilaufdioden erforderlich. Laut Übergabe wurde nur „eine Diode“ als vorhanden gemeldet, ohne Zuordnung. **Vor Betrieb oder weiterem Dimmen an beiden Lasten prüfen**, ob jeweils eine Diode vorhanden und korrekt gepolt ist (Ring zur +5-V-Seite).

Der dokumentierte 5-Hz-Betrieb führt bei kleinen Stellwerten zu einzelnen Impulsen statt sicher gleichmäßigem Lauf. Ob die Pumpe dabei tatsächlich Wasser fördert und der Lüfter nach dem Anlaufen weiterläuft, wurde am echten Aufbau noch nicht bestätigt. Die Tacholeitung des Lüfters ist nicht angeschlossen; sie darf wegen möglicher 5 V nicht ungeprüft direkt an einen Pi-GPIO gelegt werden.

## Messstatus und offene Hardwarepunkte

- **SCD40:** Beide Sensoren wurden laut Übergabe per Forced Recalibration auf 430 ppm eingestellt, unter der Annahme frischer Luft am offenen Fenster. Dabei waren teils ungewöhnlich große Korrekturen nötig. Die CO₂-Werte und mögliche Drift sollten weiter beobachtet werden; die automatische Selbstkalibrierung war zum Übergabezeitpunkt aktiv.
- **B24_1:** Das Modul lieferte bei einem Test Temperatur und Feuchte nahe den SHT45-Werten, misst aber kein CO₂. Vor weiterer Nutzung prüfen, ob seine Versorgung 3,3 V beträgt und über den eigenen Pull-up keine 5 V am GPIO 12 anliegen.
- **Taster:** Die Belegung mit internem Pull-up und Kontakt nach GND wurde in der Übergabe angenommen, der echte Taster aber nicht bestätigt.
- **OLED:** Die tatsächliche Orientierung nach der dokumentierten 180°-Drehung wurde noch nicht bestätigt.
- **Freilaufdioden und Lastverhalten:** Zuordnung und Polung der Dioden sowie Wasserfluss und Lüfterlauf bei niedrigen Stellwerten sind offen.
- **Wasserstand-Ultraschallsensor:** Die aktuelle Pinangabe ist Trigger GPIO 6 und Echo GPIO 13. Der Abstand vom Sensor zum Boden beträgt 86,2 mm. Modell, Versorgung und Pegel der Echo-Leitung sind nicht dokumentiert; vor dem Anschluss sicherstellen, dass am Pi-Eingang höchstens 3,3 V anliegen.

## Quellen

- [`Moos-Pi-Uebergabe.pdf`](../../../Downloads/Moos-Pi-Uebergabe.pdf) — Hardware- und Messangaben der Übergabe vom 1. November 2026 (außerhalb dieses Repositories).
- [`README.md`](README.md) und [`.env.example`](.env.example) — aktuelle Projektbelegung der Sensoren und GPIOs.
- [`../sshUserPfad/steuerung/steuerung.py`](../sshUserPfad/steuerung/steuerung.py), [`../sshUserPfad/steuerung/sensoren.py`](../sshUserPfad/steuerung/sensoren.py), [`../sshUserPfad/steuerung/anzeige.py`](../sshUserPfad/steuerung/anzeige.py) — dokumentierter lokaler Pi-Aufbau.
- [`../sshUserPfad/ultraschall/ultraschall.py`](../sshUserPfad/ultraschall/ultraschall.py) — eigenständige Messung mit der aktuellen Pinbelegung.
- Aktuelle Angaben zum Wasserstand-Ultraschallsensor: Nutzerangaben (Trigger GPIO 6, Echo GPIO 13; Sensor-Boden-Abstand 86,2 mm).
