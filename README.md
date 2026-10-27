# LED-Stripe an GPIO12

Das Python-Skript hält den LED-Stripe an GPIO12 dauerhaft auf 0,5 (50 % PWM-Tastgrad). GPIO12 ist der PWM0-fähige Pin.

Der Stripe muss über eine passende Treiberstufe angeschlossen sein; der GPIO steuert nur deren Eingang.

Auf dem Raspberry Pi starten:

```bash
sudo docker compose up -d --build --remove-orphans
```

Der Container benötigt den GPIO-Chip. Standardmäßig wird `/dev/gpiochip0` verwendet. Falls der zuständige Chip auf dem Pi anders heißt, `GPIOCHIP_DEVICE` in `.env` entsprechend setzen (Vorlage: `.env.example`).
