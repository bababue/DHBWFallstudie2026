# LED-Stripe an GPIO12

Das Python-Skript blendet den LED-Stripe an GPIO12 dauerhaft auf und ab. GPIO12 ist der PWM0-fähige Pin. Ein vollständiger Zyklus dauert ungefähr vier Sekunden.

Der Stripe muss über eine passende Treiberstufe angeschlossen sein; der GPIO steuert nur deren Eingang.

Auf dem Raspberry Pi starten:

```bash
sudo docker compose up -d --build --remove-orphans
```

Der Container benötigt den GPIO-Chip. Standardmäßig wird `/dev/gpiochip0` verwendet. Falls der zuständige Chip auf dem Pi anders heißt, `GPIOCHIP_DEVICE` in `.env` entsprechend setzen (Vorlage: `.env.example`).
