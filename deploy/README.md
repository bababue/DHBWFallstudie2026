# Automatisches Deployment mit systemd

Der Timer prüft regelmäßig `origin/master` und baut nur einen sauberen
`master`-Checkout. Die Unit ist für Benutzer `moos` und den Pfad
`/home/moos/DHBWFallstudie2026` vorbereitet.

Bei anderem Benutzer oder Pfad `User`, `WorkingDirectory` und `ExecStart` in
`moos-deploy.service` anpassen. `ExecStart` muss auf die `auto-deploy.sh` im
Checkout zeigen. Danach beide Units installieren; aktiviert wird der Timer,
der den Service auslöst:

```sh
sudo install -m 644 deploy/moos-deploy.service /etc/systemd/system/
sudo install -m 644 deploy/moos-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now moos-deploy.timer
```

Prüfen mit `systemctl status moos-deploy.timer` und
`journalctl -u moos-deploy.service`.
