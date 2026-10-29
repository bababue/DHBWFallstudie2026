# LED-Stripe an GPIO12

Das Python-Skript blendet den LED-Stripe an GPIO12 dauerhaft auf und ab. GPIO12 ist der PWM0-fähige Pin. Ein vollständiger Zyklus dauert ungefähr vier Sekunden.

Der Stripe muss über eine passende Treiberstufe angeschlossen sein; der GPIO steuert nur deren Eingang.

Auf dem Raspberry Pi starten:

```bash
sudo ./start.sh
```

Das Startskript nimmt zuerst mit der Pi-Kamera 0 ein JPEG auf und speichert es als `camera.jpg` im Projektordner (bei jedem Start wird die Datei ersetzt). Danach zieht es den aktuellen Stand von `origin master` als Benutzer `moos` und startet den Container `ingest`. Dafür muss `rpicam-jpeg` auf dem Raspberry Pi installiert sein.

Der Container benötigt den GPIO-Chip. Standardmäßig wird `/dev/gpiochip0` verwendet. Falls der zuständige Chip auf dem Pi anders heißt, `GPIOCHIP_DEVICE` in `.env` entsprechend setzen (Vorlage: `.env.example`).
