# bonn-delays

Datensammlung zur Nordbrücken-Sperrung Bonn (seit 03.06.2026) für
[schutzblech-bonn.de](https://schutzblech-bonn.de):

- `collect.py` — ÖPNV-Abfahrten/Verspätungen via EFA-VRR (`XML_DM_REQUEST`)
- `publish.py` — MIV-Reisezeiten via bundesstaustadt.de + `data/current.json`
- Workflow „GTFS Collect" (Cron) committet Messwerte auf den Branch `data`

Hinweis: GitHub deaktiviert geplante Workflows nach ~60 Tagen ohne Commit auf
den Default-Branch. Der Workflow „Keepalive" committet deshalb monatlich den
Zeitstempel unten und haelt so den Cron am Leben.

Letzter automatischer Keepalive: 2026-09-01

