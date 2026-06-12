#!/usr/bin/env python3
"""
Verspätungs-Logger Bonn — Korridor B56/Adenauerallee
via VRR EFA Departureboard API (öffentlich, keine Auth nötig)

Konfiguration via Umgebungsvariablen / GitHub Secrets:
  EXTRA_STOP_IDS   zusätzliche DHID-IDs (kommasepariert, optional)
  DATA_DIR         Pfad zum data-Verzeichnis (default: "data")

Feste Haltestellen (aus DELFI-Daten 2026-06-08, zHV Bonn):
  Kasernenstr./Bertha-von-Suttner  → Umweltspur BLEIBT
  Adenauerallee / Stadtbahn        → unterirdisch, stauunabhängig (Referenz)
  B56 Kölnstr./Bornheimer Str.     → Umweltspur ENTFÄLLT  ← hier messen wir
"""

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Haltestellen mit Korridor-Label ───────────────────────────────────────────
STOPS = [
    # DHID                          Korridor
    ("de:05314:61115", "Kasernenstr_bleibt"),   # Bertha-von-Suttner-Pl./Beethovenhaus
    ("de:05314:61114", "Kasernenstr_bleibt"),   # Stadthaus
    ("de:05314:61208", "Adenauerallee_ref"),    # Bundesrechnungshof/AA
    ("de:05314:62116", "Adenauerallee_ref"),    # Heussallee/Museumsmeile
    ("de:05314:61197", "B56_entfaellt"),        # Friedensplatz
    ("de:05314:61122", "B56_entfaellt"),        # Thomas-Mann-Str.
]

# Optionale zusätzliche Stops aus Umgebungsvariable
for _sid in os.environ.get("EXTRA_STOP_IDS", "").split(","):
    if _sid.strip():
        STOPS.append((_sid.strip(), "extra"))

EFA_BASE = "https://efa.vrr.de/vrr/XML_DM_REQUEST"
DATA_DIR  = Path(os.environ.get("DATA_DIR", "data"))

COLUMNS = [
    "collected_at", "corridor",
    "stop_id", "stop_name",
    "line", "direction",
    "planned_ts", "actual_ts", "delay_min",
    "status",
]

# ── EFA-Abfahrtstafel abrufen ──────────────────────────────────────────────────
def fetch_departures(stop_id: str) -> dict:
    params = {
        "outputFormat":      "JSON",
        "coordOutputFormat": "WGS84[DD.DDDDD]",
        "type_dm":           "stop",
        "name_dm":           stop_id,
        "mode":              "direct",
        "useRealtime":       1,
        "limit":             30,
        "depType":           "stopEvents",
        "itdDateTimeDepArr": "dep",
    }
    r = requests.get(EFA_BASE, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def parse_departures(raw: dict, stop_id: str, corridor: str, collected_at: str) -> list[dict]:
    rows = []
    for dep in raw.get("departureList", []):
        try:
            line      = dep.get("servingLine", {}).get("number", "")
            direction = dep.get("servingLine", {}).get("direction", "")
            stop_name = dep.get("stopName", stop_id)
            status    = dep.get("realtimeStatus", "")

            dt_plan = dep.get("dateTime", {})
            dt_real = dep.get("realDateTime", dep.get("dateTime", {}))

            def to_ts(dt: dict):
                try:
                    return datetime(
                        int(dt["year"]), int(dt["month"]), int(dt["day"]),
                        int(dt["hour"]), int(dt["minute"]),
                        tzinfo=timezone.utc,
                    ).isoformat()
                except Exception:
                    return None

            planned_ts = to_ts(dt_plan)
            actual_ts  = to_ts(dt_real)
            delay_min  = ""
            if planned_ts and actual_ts:
                from datetime import datetime as dtc
                delay_min = round(
                    (dtc.fromisoformat(actual_ts) - dtc.fromisoformat(planned_ts)).total_seconds() / 60, 1
                )

            rows.append({
                "collected_at": collected_at,
                "corridor":     corridor,
                "stop_id":      stop_id,
                "stop_name":    stop_name,
                "line":         line,
                "direction":    direction,
                "planned_ts":   planned_ts,
                "actual_ts":    actual_ts,
                "delay_min":    delay_min,
                "status":       status,
            })
        except Exception:
            continue
    return rows

def write_rows(rows: list[dict], collected_at: str):
    if not rows:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"delays_{collected_at[:7]}.csv"
    new  = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerows(rows)

def main():
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total = 0
    for stop_id, corridor in STOPS:
        try:
            raw  = fetch_departures(stop_id)
            rows = parse_departures(raw, stop_id, corridor, now)
            write_rows(rows, now)
            print(f"  [{corridor:22s}]  {stop_id}  {len(rows)} Abfahrten")
            total += len(rows)
        except Exception as e:
            print(f"  FEHLER {stop_id}: {e}", file=sys.stderr)
    print(f"{now}  gesamt: {total} Zeilen")

if __name__ == "__main__":
    main()
