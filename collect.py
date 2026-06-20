#!/usr/bin/env python3
"""
Verspätungs-Logger Bonn — Innenstadt-Gesamtbild + Korridor B56/Adenauerallee
via VRR EFA Departureboard API (öffentlich, keine Auth nötig)

Anlass: Nordbrücken-Sperrung ab 03.06.2026 + geplante Busstreifenentfernung B56.
Ziel:   Messung der Auswirkungen auf ÖPNV-Pünktlichkeit und Vergleich der Korridore.

Korridore:
  innenstadt        → Hauptknotenpunkte Innenstadt (Gesamtbild)
  Kasernenstr_bleibt → Busspur bleibt (Bertha-von-Suttner-Platz / Stadthaus)
  Adenauerallee_ref  → Referenz (Stadtbahn unterirdisch, stauunabhängig)
  B56_entfaellt      → Busspur entfällt (Kölnstr./Bornheimer Str.)
"""

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Haltestellen ──────────────────────────────────────────────────────────────
STOPS = [
    # DHID                   Korridor                  Kommentar
    # Innenstadt-Knotenpunkte (Gesamtbild)
    ("22002667",             "innenstadt"),   # Brüdergasse/Bertha-von-Suttner-Pl. (117,551,602,603,606,607,640)
    ("22000687",             "innenstadt"),   # Bonn Hbf (61,62,601,604,606,609,611,640)
    ("22001142",             "innenstadt"),   # Colmantstr./Hbf (600–607)
    # Korridor-Vergleich B56 vs. Kasernenstr. vs. AA-Referenz
    ("de:05314:61115",       "Kasernenstr_bleibt"),   # Bertha-von-Suttner-Pl./Beethovenhaus
    ("de:05314:61114",       "Kasernenstr_bleibt"),   # Stadthaus
    ("de:05314:61208",       "Adenauerallee_ref"),    # Bundesrechnungshof/AA
    ("de:05314:62116",       "Adenauerallee_ref"),    # Heussallee/Museumsmeile
    ("de:05314:61197",       "B56_entfaellt"),        # Friedensplatz
    ("de:05314:61122",       "B56_entfaellt"),        # Thomas-Mann-Str.
    # Stadtbahn U-Tunnel (unterirdisch, stauunabhängig)
    ("de:05314:61101",       "stadtbahn"),            # Bonn Hbf Stadtbahn (U-Bahnsteig)
    ("de:05314:61110",       "stadtbahn"),            # Universität/Markt (U-Tunnel)
    # Beuel / Ostseite (Kennedy-Brücke-Korridor, Nordbrücke-Ausweich)
    ("de:05314:65116",       "beuel"),                # Beuel Rathaus (529,530,537,640)
    ("de:05314:65101",       "beuel"),                # Beuel Bahnhof
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
